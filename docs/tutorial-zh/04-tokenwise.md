# 04 TokenWise：缓存断点、成本记账，和一份没赢的实验

> 教学快照：代码正文按 `76d3761`（PR #47）阅读，第一轮证据核实至 `b65f962`（PR #53）；当前检查点为 `b215c13`（PR #56）。差异与 M 编号见 [references/metrics-ledger.md](references/metrics-ledger.md)。
> 现行 Runtime 已由 `pico/call_efficiency/` 接管 Provider 调用边界，并由共享 Runtime Assembly 装配；本章“尚未装配”的判断只属于上述历史快照。现行模式、所有权与证据边界见 [Operations](../architecture/operations.md) 和 [Feature evidence](../feature-evidence.md)。

读完这一篇，你应该能回答：

- prompt 缓存怎么省钱，断点为什么最多四个、该放在哪
- 策略链的两个钩子为什么一个抛异常一个吞异常
- 成本是怎么算出来的，缓存读写的价格倍率是多少
- 三份实验报告分别证明了什么，其中一份为什么没赢
- 这一层最大的诚实点：整套策略栈目前没有生产装配点

## 一、问题：同一段前缀，每轮全价重付

多轮对话里，每次请求的 prompt 前半段几乎不变：系统指令、工具定义、启动文件、前面若干轮历史。模型侧对此有 prompt 缓存机制：你在请求的某个内容块上打一个标记，provider 把「从请求开头到这个块为止」的整段前缀存进缓存；下一次请求的前缀只要逐字节相同，这段就按大幅折扣计费，代价是写入缓存那一次要多付一点。标记本身没有任何神秘的地方，就是往内容块里塞一个字段（`pico/token_wise/cache_optimizer.py`）：

```python
_CACHE_CONTROL = {"type": "ephemeral"}
```

`ephemeral` 是短存续缓存，`pricing.py` 头注记的口径是 5 分钟 TTL：写入后五分钟内被读到才算赚，间隔一长缓存过期，下次又是全额写入。

三个约束决定了这件事不是「打开开关」那么简单：

1. **缓存键是「从开头到断点的全部内容」。** `cache_optimizer.py` 模块头注的原话：the cache key for each breakpoint is every block up to and including that breakpoint。前缀中间变了一个字，从那里开始整段作废。
2. **一次请求最多四个断点**，超了 Anthropic 的 API 直接报错。
3. **太短的前缀不缓存。** Anthropic 要求被缓存段至少 1024 token；第一份实验的测试 docstring 专门记了这条，实验用的 SOUL.md 是故意加大到把装配后的系统提示推过这个门槛的（`tests/test_token_wise_agentloop_experiment.py`）。

对照这三条看朴素做法怎么翻车：

1. **什么都不做。** 每轮全价重付整段前缀。二十轮对话，同一段两万字符的系统前缀付了二十次。
2. **打开 provider 的自动缓存。** 多数网关提供一键开关，通常只在系统消息末尾放一个断点（Pico 的 `LiteLLMProvider` 自带的这版放两个：系统末尾加最后一个工具）。断点之后的历史每轮都在变，全部按全价重算，历史越长亏得越多，第五节第三份实验量化了亏多少。
3. **到处打断点。** 四个额度花在易变内容之后等于白打：缓存要求从开头到断点完全一致，断点前面只要有一块每轮都变的内容，这个断点就永远命中不了。

真正的问题是位置选择：断点必须放在「从开头到这里都没变」的边界上。放早了浪费额度，放晚了缓存整段失效。这一章讲 Pico 怎么选位置、怎么记账、怎么用实验验证选得对不对，以及验证之后发现了什么。

## 二、策略链：两个钩子，一条不对称的错误策略

TokenWise 是一条策略链，挂在每次 provider 调用的前后。链的实现在 `pico/token_wise/registry.py`：

```python
async def before_llm_call(self, messages, tools, model):
    """Run each strategy's before-call hook. Errors propagate."""
    for s in self._strategies:
        messages, tools, model = await s.before_llm_call(messages, tools, model)
    return messages, tools, model

async def after_llm_call(self, response, usage) -> None:
    """Run each strategy's after-call hook. Errors are swallowed + logged."""
    for s in self._strategies:
        try:
            await s.after_llm_call(response, usage)
        except Exception as e:
            logger.warning("TokenStrategy '{}' after_llm_call failed: {}", s.name, e)
```

它挂进主循环的位置在 `run_turn` 的模型调用两侧（`pico/agent/loop/main.py`，节选）：

```python
call_messages, call_tools, call_model = await self.strategies.before_llm_call(
    messages, tool_defs, effective_model,
)
response = await self.provider.chat_with_retry(
    messages=call_messages, tools=call_tools, model=call_model, ...
)
usage_snapshot = self._build_usage_snapshot(response, call_model, session_key)
await self.strategies.after_llm_call({...}, usage_snapshot)
```

每个策略是 `TokenStrategy` 抽象类的实现（`pico/token_wise/base.py`），两个钩子都有默认 no-op，只关心一个钩子的策略实现一个就行；base.py 里注明选单一接口而不是四个小 ABC，是为了让安装点保持一个列表。策略之间传递的「货币」有两种：前置链上传的是请求三元组（消息、工具、模型），后置链上传的是 `UsageSnapshot`，一个八字段的 dataclass（模型、新鲜 token、输出、缓存读、缓存写、推理 token、成本、会话 key）。

两个 docstring 的差别就是全部设计：前置钩子改写请求，改写失败意味着请求本身不可信，必须炸；后置钩子只做观测（记账、遥测），记账失败不该让一次已经成功的模型调用变成失败。同一条链上，「会影响正确性的」和「只影响可观测性的」用不同的错误策略，这个区分值得在面试里点出来。

注册顺序有个 `first=True` 参数（`registry.py` 的 `register`），是为第 07 章那个工具过滤策略专门加的：它必须跑在缓存优化器之前，否则优化器先给最后一个工具打上断点，过滤器再把那个工具删掉，断点就静默消失了。请求依然合法，只是缓存悄悄退化，所以这里用的是注释加参数而不是断言（`main.py` 注册 `ToolSearchStrategy` 处的注释原话：else the marked tool may be filtered out and the breakpoint lost）。

## 三、断点放置：一个预算，四个位置

放置算法就是一个预算计数器按优先级花掉（`cache_optimizer.py` 的 `before_llm_call`，节选）：

```python
budget = self.max_breakpoints
# bp1: 工具定义的最后一条（仅当有工具）
if tools and budget > 0:
    new_tools = copy.deepcopy(tools)
    new_tools[-1] = _mark_cache(new_tools[-1])
    budget -= 1
# bp2: 最后一条 system 消息的末尾
sys_idx = _last_index(new_messages, role="system")
if sys_idx is not None and budget > 0:
    new_messages[sys_idx] = _mark_message_tail(new_messages[sys_idx])
    marked_indices.add(sys_idx)
    budget -= 1
# bp3..4: 非 system 消息的滚动尾窗
if budget > 0:
    non_sys = [i for i in range(len(new_messages))
               if i not in marked_indices and new_messages[i].get("role") != "system"]
    for idx in non_sys[-budget:]:
        new_messages[idx] = _mark_message_tail(new_messages[idx])
        marked_indices.add(idx)
        budget -= 1
```

「打标」的物理形态看 `_mark_message_tail`：字符串内容被包装成单个带 `cache_control` 的 text 块，列表内容只标最后一个块，None 或其他形状原样返回不打。所有改动都发生在副本上，调用者的原始列表不被碰，这是有专门测试钉住的行为（`test_does_not_mutate_inputs`）。

```python
def _mark_message_tail(msg: dict[str, Any]) -> dict[str, Any]:
    content = msg.get("content")
    if isinstance(content, str):
        new_content = [{"type": "text", "text": content, "cache_control": _CACHE_CONTROL}]
    elif isinstance(content, list) and content:
        new_content = list(content)
        last = new_content[-1]
        if isinstance(last, dict):
            new_content[-1] = _mark_cache(last)
        else:
            return msg
    else:
        return msg
    return {**msg, "content": new_content}
```

顺序对应稳定性梯度：工具定义最稳（整个会话不变），系统前缀次之（第 03 章那六段），历史尾部最不稳但离当前请求最近。滚动尾窗的用意在模块头注里写得很白：本轮打在 `messages[-1]` 上的断点这次是写入，下次调用历史长了一截，它就变成可命中的前缀；turn 内的工具链也一样，每次迭代只为最新那条工具结果付全价。这套布局是 v2，头注注明它是被第二份对照实验（Hermes 的 `system_and_3`）打磨出来的：无工具时的布局（系统加最后 3 条非 system 消息）与 Hermes 完全等价，有工具时才走自己的「工具、系统、最后 2 条」。

有几个值得追问的后果：

**工具优先于尾窗。** 把上限调成 2 且有工具时，工具加系统就吃光预算，滚动尾窗一个都不放。`test_max_breakpoints_is_respected` 钉住的就是这个：budget=2、有工具、5 轮历史，断言恰好 2 个标记。这是个真实的配置陷阱：调小上限不是「少放几个」，是「按优先级砍掉后面的全部」。

**找的是最后一条 system 消息**，不是第一条。Pico 的六段前缀拼成一条 system 消息，所以这里等价；但换个装配方式（多条 system 消息）行为就会不同。对照复刻的 Hermes 策略恰好写死了 `messages[0]` 是 system 才标，两种写法在单条 system 的世界里看不出差别。

**没有上限钳制。** 构造函数只校验 `max_breakpoints >= 1`，「不超过 4」是 Anthropic 的限制，靠配置默认值保证，代码里不拦；填 5 会在请求发出去之后由 API 报错。

**能力判定与 provider 各查各的，答案可能相反。** 缓存优化器判断「这个模型支不支持缓存」走 `find_by_model`，这个函数按模型名关键词匹配标准 provider 条目，并且明确跳过网关和本地 provider（`pico/providers/registry.py` 的 docstring：Skips gateways/local）；而 provider 自己的判定先看网关声明，检测到网关就以网关的 `supports_prompt_caching` 为准（`litellm_provider.py` 的 `_supports_cache_control`）。两边信息源不同就会岔开：一个 Claude 模型走 AiHubMix 这类没声明支持缓存的网关，provider 认为不能缓存（自己的自动缓存不开），策略却按模型名里的 claude 关键词匹配到 Anthropic 条目认为能，照样打断点；反过来，一个名字匹配不到任何缓存关键词的模型走 OpenRouter（网关声明了支持），provider 愿意自动缓存，策略这边却不打。这是当前实现的不一致，如实记着。

## 四、记账：三层聚合，四项乘数

`UsageTracker`（`pico/token_wise/usage_tracker.py`）把每次调用的用量累加进三个桶：按会话、按天、按进程生命周期。落盘是每天一个 JSONL（`{telemetry_dir}/usage-YYYY-MM-DD.jsonl`），一行一次调用，字段是 UTC 时间戳加上 `UsageSnapshot` 的全部八个字段；`flush_every` 默认 1，每次调用即写盘，调大可以摊薄 IO 但崩溃时丢的行也多。

成本不在 tracker 里算，价格解析是 `pricing.py` 里的一条四级降级链：先问 LiteLLM 的价格表（先试带 `openrouter/` 前缀的 id，再试裸 id，返回 (0, 0) 视为未命中），再查 OpenRouter 的在线模型目录（进程内缓存一小时 TTL，另有一层落盘缓存用临时文件加 `os.replace` 原子替换，网络失败时回落陈旧缓存，绝不向成本路径抛异常），再查兜底价格表，最后放弃并对该模型只警告一次。兜底表当前只有一条记录，头注还叮嘱加新条目前先查 LiteLLM：

```python
_FALLBACK_PRICING: dict[str, tuple[float, float]] = {
    # OpenRouter model pages (snapshot 2026-03)
    "z-ai/glm-4.5-air": (0.13e-6, 0.85e-6),  # $0.13/$0.85 per 1M
}
```

价格公式里有两个必须记住的乘数：

```python
cost = (
    input_tokens * prompt_rate
    + output_tokens * completion_rate
    + cache_read_tokens * prompt_rate * 0.1      # 缓存读打一折
    + cache_write_tokens * prompt_rate * 1.25    # 缓存写贵两成半
)
```

缓存读一折、缓存写 1.25 倍，这就是缓存的经济学：一次写入的溢价，要靠后续多次读取摊平。会话越长、前缀越稳，收益越大；如果每轮都在写而读不到，反而更贵（第五节有个真实案例正是这样）。

还有个口径细节值得讲：不同 provider 报的 prompt_tokens 含义不同，Anthropic 原生报的是「新鲜 token」（不含缓存），OpenRouter 和 LiteLLM 报的是总量。`AgentLoop._build_usage_snapshot` 用一个启发式归一化：

```python
if prompt_t >= cache_read + cache_write and (cache_read + cache_write) > 0:
    fresh = prompt_t - cache_read - cache_write
else:
    fresh = prompt_t
```

这是推断不是声明，而且同样的逻辑在 tracing 那边还有一份复制（`pico/tracing/usage.py`，头注自己写明 Mirrors `AgentLoop._build_usage_snapshot` semantics）。两处副本的同一个启发式，是明摆着的漂移隐患。

三个小坑一并交代：按天聚合用的是 `date.today()` 本地日期，而每行的时间戳是 `datetime.now(timezone.utc)`，跨时区时日聚合和自己的时间戳对不上；生命周期总量只是本进程的，重启归零，真正持久的账本是那份 JSONL；刷盘失败会记警告并丢掉缓冲行（`_flush` 的 except 分支，日志原话 dropping N rows），这是「记账绝不拖垮 turn」的取舍，但确实是数据丢失。

## 五、三份实验，一份没赢

这一层的证据主体是三份带日期的实验报告，都在 `pico/token_wise/` 下。三份都挂着同一句免责声明（历史快照、驱动路径 `AgentLoop.process_direct` 已移除、未在当前 `run_turn` 上重跑），第三份还加了一句更硬的：Do not use these numbers as current release evidence。

**第一份（EXPERIMENT_REPORT.md，2026-04-15）：缓存到底有没有用。** 三个变体各跑 6 轮，模型 claude-sonnet-4-5 走 OpenRouter 钉到 Anthropic 后端。无缓存基线花 0.105561 美元；provider 自动缓存降 50.5%；TokenWise 四断点降 50.7%（M6）。两个缓存方案几乎打平，只差 0.2 个百分点。逐轮数据比总数更有讲头：基线每轮 fresh 5,800 到 5,885；四断点变体第 1 轮写入 5,745 个缓存 token，那一轮花 0.0218 美元，比基线单轮的 0.0175 还贵，从第 2 轮起 fresh 只剩 60 上下，命中缓存的轮次读 5,700 多个 token，单轮成本掉到 0.002 量级。写入溢价第一轮先亏、后五轮摊平，第四节那两个乘数在这张表里是看得见的。逐轮表里还有一处如实记着的毛刺：两个缓存变体各有一轮读挂了整段重写（V2 第 4 轮、V3 第 3 轮，cache_read 归零），报告没有解释原因，缓存命中本来就不是确定性的。

报告的 Caveat 一节记了一个坑：OpenRouter 默认路由会把 Anthropic 请求分散到多个后端实例，导致每次调用都触发 `cache_write` 而 `cache_read` 恒为零。也就是说，一个号称省一半的功能，在默认配置下会因为写入溢价（1.25 倍）让你付得更多。实验代码的解法是显式钉住后端并禁用回退：`provider={'order': ['Anthropic'], 'allow_fallbacks': False}`，经 `LiteLLMProvider.extra_body` 传入；直连 Anthropic API 的用户没有这个问题。

**第二份（EXPERIMENT_REPORT_CACHE_STRATEGIES.md，2026-04-16）：和竞品方案比。** 把 Hermes Agent 的 `system_and_3` 策略原样复刻进来（`system_and_tail_cache.py`）做三场景对照。纯对话场景（8 轮无工具）双方都比基线省 73.3%，差 0.2%；turn 内工具链场景（3 个工具乘 3 轮，每轮最多 4 次模型调用）63.7% 对 63.6%，我们略先 0.2%；最贴近真实的混合场景（1 个工具、每轮 decide 加 respond 两次调用、6 轮），对方 66.4% 对我们 64.9%，输 4.1%。

自家四断点方案没有赢过一个复刻来的更简单方案，而这份记录了失败结论的报告被保留在仓库里。这是本章最好的素材，讲法可以是：我们做了对照实验，结论不利于自己的设计，我们把它留在了仓库里，因为一份说自己赢了的实验和一份说自己没赢的实验，后者才证明这套实验方法是可信的。

**第三份（EXPERIMENT_REPORT_WORKLOADS.md，2026-04-15）：那第一份为什么只差 0.2%。** 追问式的第三轮实验，测试文件的 docstring 直接写明动机：第一个工作负载让 provider 自动缓存显得很好（原话 the workload made V2 look good，huge stable system prompt, almost no history），巨大稳定的系统提示占满请求，历史几乎为零，单断点方案没有暴露短板的机会。于是换两个负载重跑。场景 A 是中等系统提示加长历史：预先塞入 16 轮合成问答再测 6 轮，自动缓存省 46.5%，四断点省 58.7%，比自动缓存便宜 22.9%。场景 B 是高频工具调用：一个每次返回约 500 token 固定数据的工具，6 条消息每条强制一次调用，自动缓存省 33.8%，四断点省 66.9%，便宜 50.0%。差距的来源就是断点位置：自动缓存的断点在系统末尾，不断增长的历史和工具结果全在断点之外每轮全价；滚动尾窗把它们也圈进了缓存。

同样的代码，两次实验给出两个结论，差别全在工作负载的设计。第一次不是测错了，是测了一个让对照组显得很好的场景。第三份报告里还留了一个反直觉细节：最省钱的场景 B 里，逐次调用的新鲜 token 在 68 和 1309 之间振荡，因为新追加的工具结果落在缓存前缀之外。最便宜的那份数据也不干净。

## 六、取舍：为什么不做 X

**为什么不把断点上限调大？** 上游硬限制是四个，超了报错。真正的问题从来不是数量而是位置，四个足够覆盖「工具、系统、近两轮」这个稳定性梯度。

**为什么后置钩子吞异常？** 记账和遥测的失败不该让一次成功的模型调用变成失败。代价是遥测可能悄悄丢，所以刷盘失败会打警告。这条取舍在第 01 章的交付层是同一个模式：可观测性的失败不回滚已经发生的事实。

**为什么保留竞品策略的复刻实现？** 它是 A/B 的参照系，删掉它，那份「我们没赢」的报告就无法复现。署名在复刻文件的模块头注里（来源 NousResearch/hermes-agent 的 `agent/prompt_caching.py`，v0.9.0，2026-04-13），MIT 许可证文本在 `LICENSES/MIT-hermes-agent.txt`。

**为什么不做智能路由、工具结果生命周期这些？** 配置 schema（`pico/config/pico.py` 的 `TokenWiseConfig`）里确实躺着这些开关：智能路由、工具结果归档各带 `enabled: bool = False`，技能懒加载是 `skill_lazy_loading: bool = False`；预算那组更微妙，阈值默认就填着值（告警 0.50 美元、硬顶 2.00 美元），但对应的 BudgetAlerter 策略类不存在，这些数字是纯摆设。装配代码的 docstring 老老实实写了计划中的六个策略（SmartRouter、ToolResultLifecycle、SkillLazyLoader、CacheOptimizer、UsageTracker、BudgetAlerter），并注明只有两个存在。声明了没接线的旋钮要标出来，不能让人以为配置项等于能力。

## 七、最大的诚实点：这套栈没有生产装配点

得把这条放在明面上：策略栈的装配函数在生产代码里没有调用者。把配置翻译成注册表的 `install_from_config` 在 `pico/cli/_token_wise_stack.py`，在 `pico/` 里 import 它的只有 `__init__.py` 的重导出，真正调用它的只有两个测试文件；唯一的 AgentLoop 构造点 `pico/cli/_runtime_assembly.py` 的参数列表里没有 `strategies`，所以真实运行时那个注册表是空的。唯一可能被注册进去的成员是第 07 章那个 `ToolSearchStrategy`，而它的注册被 `tool_search.enabled` 挡着，默认 False（`pico/config/schema.py`）。

后果是：本章讲的配置默认值（`enabled: True`、`cache_optimization: True`、`usage_tracking: True`）目前全部处于未生效状态；`~/.pico/telemetry` 下不会有文件；没有任何 CLI 命令读它。

面试里怎么讲这件事，取决于诚实的深度。可以这么答：这层的机制、配置、遥测格式和三份对照实验都完成了，但装配的最后一根线没有接上，所以在当前主干上它是一套已验证未启用的能力。这本身也说明我们的证据纪律是有效的，正是因为不允许把「代码存在」说成「能力生效」（第 11 章的证据分级），这个缺口才没有被简历上的一句「实现了成本优化」盖过去。

## 八、怎么被验证

确定性测试四个文件，按对象分：

- `tests/test_token_wise_registry.py`，9 个用例：两个钩子都按注册顺序执行、前置抛后置吞且后续策略照跑（`test_after_hook_failure_is_swallowed_other_strategies_still_run`）、空注册表纯透传、模型改写沿链传递。
- `tests/test_token_wise_cache_optimizer.py`，14 个用例：不支持的模型原样返回、输入不被就地修改、字符串内容包装成 text 块、上限为 2 时的优先级、短对话与无 system 无工具的边界、幂等重复应用不叠加标记。
- `tests/test_token_wise_usage_tracker.py`，12 个用例：三层聚合、JSONL 行落盘、`flush_every` 缓冲、目录不可写时降级不炸。
- `tests/test_token_wise_pricing.py`，26 个用例，含 7 个磁盘缓存用例：冷写、热命中不发网络、过期重取、版本不符忽略、损坏文件降级、网络失败回落陈旧缓存、原子写。

三份实验报告由三个 `real_llm` 标记的测试生成（`test_token_wise_agentloop_experiment.py`、`test_token_wise_cache_strategies.py`、`test_token_wise_workload_scenarios.py`），默认被保留套件排除（M18 的证据边界），不花钱不跑，缺 `OPENROUTER_API_KEY` 时自动跳过。

一个耐人寻味的细节：这三个实验测试文件都已经移植到当前的 `run_turn` 路径上（三个文件里驱动 turn 的调用都是 `loop.run_turn`），但仓库里的三份报告仍是 `process_direct` 时代生成的产物，报告开头那段「未在当前路径重跑」的免责声明就是这么来的。代码搬了家，数字留在原地，这正是 M6 在口径表里被标成历史快照的原因。

## 九、预演追问

**「你们怎么做成本优化的？效果多少？」**
两条线。缓存放置：在每次模型调用前按稳定性梯度放至多四个缓存断点，工具定义、系统前缀、最近两条消息，位置的原则是放在「从开头到这里都没变」的边界上。成本记账：每次调用后把用量累进会话、日、进程三个桶并落 JSONL，成本按 provider 价目算，缓存读按一折、缓存写按 1.25 倍计。效果必须带口径：历史快照里四断点方案相对无缓存基线降 50.7%，但那是 donor 期、6 轮、驱动路径已移除的测量，不能当作当前发布证据；而且同一批实验里它只比 provider 自动缓存好 0.2 个百分点。

**「为什么最多四个断点？位置怎么选？」**
四是上游硬限制，超了报错。位置按稳定性梯度选：工具定义整个会话不变放第一个，系统前缀次之，剩下的给最近的消息，因为缓存要求「从开头到断点」完全一致，放在易变内容之后等于白放。断点本身只是内容块上的一个 `{"type": "ephemeral"}` 字段，被缓存段还要求至少 1024 token，太短不缓存。有个配置陷阱值得一提：把上限调小不是均匀减少，是按优先级砍掉后面的全部，上限为 2 且有工具时滚动尾窗一个都不会放，有测试钉住这个行为。

**「你怎么知道这套缓存策略是有效的？」**
做了三轮对照实验，而且结论不全是好消息。第一轮证明缓存有效但我们的方案只比 provider 自动缓存好 0.2%。第二轮把竞品方案原样复刻进来三场景对比，两场打平，最贴近真实的那场我们输 4.1%，这份报告我们留在仓库里。第三轮追问第一轮为什么差距那么小，发现是那个负载对 provider 自动缓存太友好：巨大稳定的系统提示、几乎没有历史，单断点方案完全没暴露短板。换成有历史积累和工具输出的负载后，我们的方案比自动缓存便宜 22.9% 到 50%。这三轮给我的最大收获是：实验结论强依赖工作负载设计，一次实验只能回答一个具体场景下的问题。

**「缓存有没有可能越开越贵？」**
有，两种真实情况都撞过。第一种是乘数决定的：写入按 1.25 倍计费而 TTL 只有约五分钟，请求间隔一长每次都在写新缓存而读不到，纯付溢价。第二种是第一份实验记录在 Caveat 里的：OpenRouter 默认路由把请求分散到多个后端实例，cache_write 每次都发生而 cache_read 恒为零，比不开缓存还贵；解法是钉住后端并禁用回退，实验代码传的是 order 指定 Anthropic 加 allow_fallbacks 为 False。判断缓存在不在挣钱，看账本里 cache_read 和 cache_write 的比值就够了。

**「你们记的成本准吗？」**
分层答。价格来源是四级降级链，模型未知时只警告一次不瞎猜。口径上有一处推断：不同 provider 报的 prompt token 含义不同，有的含缓存有的不含，我们用一个启发式归一化成「新鲜 token」，这是推断不是 provider 声明，而且这段逻辑在 tracing 那边还有一份复制，是已知的漂移隐患。还有三个小口径要交代：日聚合用本地日期而行时间戳是 UTC、进程总量重启归零、刷盘失败会丢行（为了不拖垮 turn）。

**「这套东西现在跑起来了吗？」**（如果被追问实际生效情况）
诚实答：机制、配置、遥测格式、三份实验都完成了，但装配的最后一根线没接，当前主干上运行时的策略注册表是空的。这不是我藏着的，是我们的证据纪律要求「代码存在」不等于「能力生效」，所以它在文档里被标成已验证未启用。要启用只差在装配点传一个参数，但没跑过证据之前我不会把它写成已上线的能力。

## 口播稿

> TokenWise 是挂在每次模型调用前后的策略链，前置钩子改写请求、错误直接抛，后置钩子只做记账、错误吞掉记日志，因为影响正确性和影响可观测性的失败不该同等对待。核心机制是缓存断点放置：按稳定性梯度花掉最多四个断点，工具定义、系统前缀、最近两条消息，原则是断点必须落在从开头到这里都没变的边界上。记账侧按会话、日、进程三层聚合并落 JSONL，成本算式里缓存读打一折、缓存写一点二五倍，这就是缓存的经济学，一次写入的溢价靠后续多次读取摊平。这一层我最想讲的是三份实验：第一份证明缓存有效但我们只比 provider 自动方案好零点二个百分点；第二份把竞品策略原样复刻做对照，最贴近真实的场景我们输了四个百分点，这份报告我们留在仓库里；第三份追问第一份为什么差距那么小，发现是那个负载对 provider 自动缓存太友好，换成有历史和工具输出的负载，我们比它便宜两成到五成。最后一个诚实点：这套策略栈目前还没有生产装配点，配置默认值全部未生效，我们把它标成已验证未启用，而不是写成已上线。

## 复习路径（10 分钟）

1. 讲得出两个钩子的错误策略差异，以及为什么这个差异是对的。
2. 背断点四个位置和稳定性梯度，说得出「上限调小按优先级砍」这个陷阱，以及断点就是内容块上一个 ephemeral 字段、被缓存段至少 1024 token。
3. 记住两个乘数：缓存读 0.1、缓存写 1.25，并能推出「读不到就更贵」和 OpenRouter 多实例路由那个真实翻车。
4. 三份实验各一句话：证明有效但只比自动缓存好 0.2%、复刻竞品我们没赢 4.1%、换负载后便宜 22.9% 到 50%。
5. 记住 M6 的完整口径和「没有生产装配点」这个诚实点，两者都别在面试里漏掉。
