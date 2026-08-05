# 09 Tracing 与可观测：不打扰主流程的记录者

> 教学快照：代码正文按 `76d3761`（PR #47）阅读，第一轮证据核实至 `b65f962`（PR #53）；当前检查点为 `b215c13`（PR #56）。V-TE0 与 #23 已完成，完整发布聚合仍待 V-R0。本章的 V-TE0 机制来自 PR #51，晚于代码基线。差异与 M 编号见 [references/metrics-ledger.md](references/metrics-ledger.md)。

读完这一篇，你应该能回答：

- 一次 agent 运行出了错，你从哪几层往回查，为什么日志不够
- 「非侵入」不是态度是契约，代码上靠哪四条保证
- 装饰器怎么做到「标一行、函数体不动」，三个钩子各干什么
- 为什么这个项目主动不上 OpenTelemetry，还写了一个测试钉住这个决定
- 现场怎么把这些数据看起来，一条命令背后的端口探活细节
- 这一层最大的缺口：证据能观察，但还没关联起来

## 一、问题：它到底干了什么

用户说「昨天那个任务它答错了」。你手里有什么？

**只有日志的话**，你有一堆时间戳文本行。哪几行属于那一次运行、模型调了几次、工具调用和它的结果怎么配对、上下文那轮走的是快路还是降级路径，全靠人眼在文本里拼。会话稍微一并发，两个用户的行交错在一起，拼都拼不出来。

朴素做法的四种失败：

1. **狂打 print。** 排查时加、排查完删，下次重来。而且它不带结构，「哪一次运行」这个最关键的维度不在数据里。
2. **每个模块自己定义日志格式。** 工具那边叫 `tool_name`，模型那边叫 `model_id`，记忆那边叫 `backend`。汇总时先写一层清洗。
3. **上一整套 OpenTelemetry。** 引入依赖、起 collector、配 exporter。对一个本地跑的单机 agent 来说，运维成本比它解决的问题大，而且默认导出会把 prompt 和工具输出送出机器。
4. **观测代码写进业务函数体。** 一个 30 行的函数里 12 行在记 span，业务逻辑被埋掉，而且观测出错会连坐业务。

第四条最隐蔽。观测的第一原则是它不能改变被观测的东西，一个会抛异常的 tracing 层比没有 tracing 更糟。

先给替代品的实物。这一层用「span」代替日志行：一次有始有终的操作（一次模型调用、一次工具执行）记成一行 JSON，字段集合被测试冻结。下面是一条 `llm.call` 的示例（字段名与层级按 `pico/tracing/spans.py` 的 `build_span` 原样，值为示意）：

```json
{
  "schemaVersion": "audit.span.v1",
  "traceId": "trace-19894f3a2b1-a3f29c01",
  "spanId": "span-19894f3a2c8-b41d02",
  "parentSpanId": "span-19894f3a2b7-9cd311",
  "name": "llm.call",
  "kind": "INTERNAL",
  "startTime": "2026-07-24T10:12:03.481226+00:00",
  "endTime": "2026-07-24T10:12:05.112884+00:00",
  "status": {"code": "OK", "message": ""},
  "attributes": {
    "span.type": "model",
    "framework": "pico",
    "session.id": "cli:direct",
    "session.key": "cli:direct",
    "channel": "cli",
    "channel.id": "cli",
    "chat_id": "direct",
    "audit.schema_version": "audit.span.v1",
    "llm.provider": "openrouter",
    "llm.model": "openrouter/anthropic/claude-sonnet-4-5",
    "llm.usage.total_tokens": 8213
  },
  "events": []
}
```

这一条记录同时回答了上面四种失败：`traceId` 天生携带「哪一次运行」，同一次 turn 里的所有 span 共享它；`parentSpanId` 把工具调用挂到发起它的那次模型调用下面，配对不再靠人眼；字段名由一处集中定义（第五节）；两个用户并发时是两棵互不相干的树。id 的来历也简单，`context.py` 里 `new_trace_id()` 拼的是 `trace-<毫秒时间戳十六进制>-<8 位随机十六进制>`，span id 同构，随机段 6 位。`spans.py` 的模块注释解释了为什么 schema 叫 `audit.span.v1` 而不是 pico 自己的名字：同一套记录格式被一族采纳者共写，「One viewer renders any framework's traces because every collector writes this same schema」，Pico 只是在原有五种 `span.type` 之外加了 `memory`、`plugin`、`skill` 三种。

## 二、机制一：非侵入是四条代码级契约

模块 docstring 把承诺列成了三条，代码里还有第四条：

```python
"""Public instrumentation API — the standard adopters call.

Guarantees (so an adopter is safe):
- **No-op when disabled** — yields a no-op handle, no I/O.
- **Never breaks the caller** — swallows tracing-internal failures; re-raises the
  application's own exception (after recording ``status=ERROR``).
- **Import-safe** — importing and calling never requires config to be present.
"""
```

逐条看它怎么落地。

**关掉就是空操作。** `span()` 第一件事是查开关，关着就 yield 一个 `_NoopSpan` 直接返回。这个空对象把全部方法都实现成返回自己：

```python
class _NoopSpan:
    """Returned when tracing is disabled or an internal open failed."""

    trace_id = ""
    span_id = ""

    def set(self, *_a, **_k):
        return self

    def artifact(self, *_a, **_k):
        return self
```

`event`、`error`、`retype`、`checkpoint`、`cancel` 同样返回自己，`elapsed_ms` 返回 0。调用方的链式写法 `s.set(...).artifact(...)` 照常成立，没有分支判断，也没有任何 I/O。真 `Span` 类的 docstring 承诺同一件事的另一半：「Every method is no-throw and returns self」。

**内部失败自己吞，业务异常原样抛。** 这个区分在 `span()` 的结构里看得最清楚：

```python
try:
    yield handle
except Exception as exc:
    handle.error(exc)
    raise
finally:
    try:
        if token is not None:
            _ctx.reset(token)
        if not handle._cancelled:
            _spans.emit(_spans.build_span(...))
    except Exception:  # noqa: BLE001
        _log.debug("tracing: span(%s) emit failed", name, exc_info=True)
```

业务抛的异常先记成 ERROR 状态再 `raise` 原样往上走，一个字节都不改；而落盘环节自己炸了只写一条 debug 日志。这两个 try 的嵌套关系就是「非侵入」的全部实现。

**打开 span 本身也不能炸。** 开 span 的那段（取当前上下文、造 id、push contextvars）整体包在 try 里，失败就退化成 `_NoopSpan` 继续，注释写着 open must never break the host。

**第四条契约在写产物那里。** `artifact()` 把大载荷写到 span 之外，同样吞掉自己的异常，注释是同一句：tracing must never break the host。

值得记的一个细节：所有异常吞掉时用的是 `_log.debug` 而不是 warning。理由说得通，观测失败是运维问题不是用户问题，把它抬到 warning 会污染用户看到的输出，而这层的初衷正是不打扰。

## 三、机制二：标一行，函数体不动

采纳这套东西的方式是给方法加个装饰器，业务函数体一行不改。仓库里共有 22 处这样的埋点（口径：`grep -rn "trace.instrument" pico/ --include="*.py"` 排除 `pico/tracing/` 自身，工作树 `76d3761`）。三处实物：

```python
# pico/providers/base.py
@trace.instrument("llm.call", extract=semconv.llm_call)
async def chat_with_retry(self, messages, tools=None, model=None, ...): ...

# pico/agent/tools/registry.py
@trace.instrument("tool.call", extract=semconv.tool_call)

# pico/agent/loop/main.py，唯一同时用满三个钩子的埋点
@trace.instrument("session.turn", seed=semconv.turn_seed, on_open=semconv.turn_open, extract=semconv.turn)
async def _process_message(self, req: TurnRequest, ...): ...
```

装饰器提供三个钩子，各管一段：

| 钩子 | 时机 | 干什么 |
|---|---|---|
| `seed(bound)` | 开 span 前 | 返回会话身份（session_key、channel、chat_id），用来播下一个根 span，也就是一次 turn |
| `on_open(span, bound)` | 开完立刻，函数体之前 | 记录输入，必要时 checkpoint 一个进行中的根 span 供实时查看 |
| `extract(span, bound, result, exc)` | `finally` 里 | 填最终属性和产物；`result` 成功时是返回值，`exc` 失败时是异常 |

三个钩子有两处设计值得讲。第一，钩子拿到的 `bound` 是按参数名绑定并填好默认值的调用参数字典（`inspect.signature(...).bind` 加 `apply_defaults`），提取器写起来是 `bound["messages"]` 而不是数位置。第二，`extract` 挂在 `finally` 而不是成功分支，docstring 给了理由：so input is captured even on error，出错那次的输入恰恰是最需要留下来的。

`on_open` 里那个 checkpoint 值得单独解释。turn 是长 span，中途的子 span 落盘时它自己还没关闭，看板上会没有根可挂。`turn_open` 在函数体执行前调 `span.checkpoint()`，用同一个 `span_id` 先发一版进行中状态（`turn.in_progress: True`），turn 结束时再发最终版；`checkpoint()` 的 docstring 写明查看器按 id 去重、保留末次写入，所以中途版本不会变成重复节点。

三个钩子各自也被 try 包着，钩子写错了只写 debug 日志，不影响业务。装饰器同时支持同步和异步函数，关闭时直接调原函数，连 span 上下文都不进。

嵌套是自动的，靠 contextvars：在一个 span 的 `with` 块里开的 span 自动成为它的子节点，业务代码不需要传递任何句柄。这一点跨任务也成立，`context.py` 的模块注释指出 contextvars 在 `await` 之间存活，并且 `asyncio.create_task` 创建子任务时会快照当前上下文，所以 turn 中途 spawn 的子代理，它内部的 `llm.call`、`tool.call` 自动挂在 `subagent.run` 节点下，一行胶水都没写。span 的名字是 `<域>.<动词>`，域名映射成粗粒度的 kind：8 个域映射到 7 个值（session、model、tool、subagent、skill、memory、plugin，其中 tracing 域折进 plugin），映射表里没有的域直接用域名本身当 kind，`personalize.*` 那组就是显式传 `kind="memory"` 归进记忆类。这套词表被一个测试钉住（`test_span_kind_vocabulary_is_frozen`），加新 kind 必须显式改测试。

上下文里还搭了一个自我标注机制。`TraceCtx` 带一个 `source` 字段，规则在 `context.push()` 里只有一行：非 model 的 span 成为后代的 source，model span 继承父的 source（它永远不做自己的来源）。效果是 `llm.call` 的提取器可以直接读 `span.invocation_source` 得到「这次模型调用是替谁干活的」（turn、`skill.gate`、`memory.extract`），写进 `llm.invocation_source` 属性，不需要爬树。两个测试钉住它：根 span 上是 `None`，嵌套在 `skill.gate` 下的 `llm.call` 标出 `skill.gate`。

还有一个 `retype`，用于「调用之后才知道自己是什么」的场景。第 07 章提过一次：`read_file` 读到 SKILL.md 时，那个 span 会被 retype 成 `skill.read`，原工具名保留在 `skill.read.via_tool` 属性里，注释解释了为什么安全，span id 是固定的，改名不影响嵌套。

`cancel()` 服务条件 span：两个 `skill.inject` 提取器只在真的注入了内容时填属性，什么都没注入就 `span.cancel()`，这条 span 一行都不落盘，看板上不会出现一堆空注入节点。`detached=True` 与它配套：标记式的叶子 span 不成为活跃父节点，所以它内部发生的工作挂到它的父节点上。注释说明了动机，用于可取消的 span（比如技能注入），否则一个在取消之前就开始的子 span 会挂在一个永远不会被发出的父节点上，成为悬空节点。

## 四、机制三：落盘就是 JSONL，看板是可选件

存储层只用标准库，注释写明它是从共享的 tracing 插件核心拷过来的，为的是这个包在 pip 安装后自包含。布局很朴素：

```
<state_dir>/logs/audit-events.log       每行一条事件记录
<state_dir>/logs/audit-spans.log        每行一个 span
<state_dir>/logs/audit-artifacts/...    大载荷单独成文件
<state_dir>/logs/archive/<date>/...     轮转后的日志
```

默认状态目录是 `~/.pico/traces`，可以用 `PICO_TRACING_DIR` 或 `PICO_HOME` 改。轮转有两个触发条件，任一满足就把活跃文件改名进 `archive/<当天>/`：跨了 UTC 日；或现有大小加上本条超过上限，默认 50 MiB，`TRACE_LOG_MAX_BYTES` 环境变量可改。一处诚实说明：布局里的 `audit-events.log` 是从共享核心拷贝时带过来的能力，`pico/` 里没有 `append_event` 的调用方（grep 口径，工作树），Pico 的事件走 span 记录内嵌的 `events` 数组。

大载荷不进 span 行，走 artifact 单独存一份，span 上留 `<key>.artifact_path` / `artifact_sha1` / `artifact_bytes` 三个引用属性（写失败再加一个 `artifact_error`）。正文预览是另一条路：各提取器把 `llm.output_preview`、`tool.result_preview` 这类截断属性直接放在 span 上，截断长度读 `config.preview_len()`，默认 500 字符，`PICO_TRACING_PREVIEW` 或配置 `previewLen` 可改。这条设计让 span 文件保持可 grep 的体量，同时完整输入输出没有丢。

本章旧稿在这里照抄了一句注释，这版修正：store.py 的布局注释写着大载荷「SHA1-deduped」，实现并不在写入时查重。看文件名的构造：

```python
file_name = "-".join(
    [
        datetime.now(timezone.utc).strftime("%H%M%S%f"),
        safe_segment(meta.get("traceId") or meta.get("runId") or "trace"),
        safe_segment(meta.get("sessionId") or meta.get("sessionKey") or "session"),
        safe_segment(label or kind),
        sha1[:10],
    ]
)
```

时间戳精确到微秒打头，每次调用都写一个新文件，相同内容重复写就是两个文件。SHA1 进了文件名后缀和 span 属性，用途是事后识别重复与校验完整性，不是写入去重。这处注释与实现的漂移和第七节规范说谎是同一类问题，只是这次漂到了教程里。

配置读取本身也贯彻了不打扰：读配置文件的函数整体包在 try 里返回空字典，注释先写 Never raises，紧跟一句 tracing must not break startup。开关的优先级是环境变量 `PICO_TRACING` 压过配置文件，默认开启，`PICO_TRACING=0` 是全局熄火开关（`0`、`false`、`off`、`no` 都认）。

看板用 `pico tracing` 一条命令打开。它是一个捆在 `pico/tracing/viewer/` 里的 Node 查看器，零 npm 依赖，但需要 Node >= 22 运行时（与 TUI 同一要求，复用同一套 Node 发现逻辑），默认端口 4318。启动前的探活写得比「看端口活没活」多一层：端口活着不等于是自己的看板，可能是老版本的残留进程或一个无关服务占着，所以命令先打 `/api/health`，只有返回 `{"ok": true}` 才认作自己的 viewer 直接复用；是陌生进程就往后最多扫 20 个端口找空位另起。这条可以一般化：探活要验身份，不能只验端口。看板是运维辅助，不是托管控制平面，这条边界在项目状态文档里被明确写下来过（原话：The local tracing viewer is an operator aid, not a hosted control plane）。

## 五、机制四：语义约定，让字段有唯一名字

`semconv.py` 是这层最大的单文件（632 行，工作树 `wc -l`），它做的是把「谁在什么时候记什么字段」集中到一处。提取器的全集数一遍：`llm_call` 和流式的 `llm_call_stream`；`tool_call`；turn 三件套 `turn_seed` / `turn_open` / `turn`；memory 六个（recall、store、feedback、extract、profile_refresh、consolidate）；`context_curate`；skill 四个（两种 inject、rewrite、gate）；`plugin_load` 是个工厂，按贡献类型造两个实例（memory_backend、tool）；`personalize` 四步共用一个；`subagent`。对应第 03、05、07 章讲过的每一条关键路径，都有一个名字固定的观测点。

集中的好处在几个地方兑现。字段名统一（工具名永远是 `tool.name`，不会一处叫 `tool_name` 一处叫 `name`）；截断规则统一（工具参数预览 300 字符、错误预览 200 字符、记忆查询预览 300 字符）；敏感处理统一。净化那步的实现在 `Span.artifact()` 里：载荷先过 `sanitize_persisted_payload`（`pico/utils/persisted_payload.py`），一个正则把 `data:image/...;base64,...` 内联图片 URI 换成 `[image data omitted]`，并且返回的是非变异拷贝，运行中的消息对象一个字节不动。有测试同时断言三件事：落盘文本里搜不到 base64 数据、替换标记出现了预期次数、活载荷对象原样。

两处只有集中才做得动的归一化值得展开。一是 `provider_label`：Pico 通过单一 `LiteLLMProvider` 类走所有网关，类名答不出「这次到底是谁服务的」，但 LiteLLM 把后端编码在模型名前缀里（`openrouter/anthropic/claude-...`），所以取第一段作逻辑后端标签，没有前缀再退回类名。二是 `_llm_input_payload` 把一条扁平 messages 列表拆成三个不重叠视图给看板（systemPrompt、prompt 即最新用户消息、historyMessages 是剩余部分），同时原始 `messages` 全量保留作 ground truth，拆错了也能对回去。

有一处跨层的复制值得点名。用量归一化在这层有一份：

```python
"""LLM usage normalization + best-effort cost.

Mirrors ``AgentLoop._build_usage_snapshot`` semantics (fresh-vs-total prompt
token convention differs by provider). ...
"""
```

它自己写明是 AgentLoop 里那份的镜像。启发式本体只有四行：

```python
if prompt_t >= cache_read + cache_write and (cache_read + cache_write) > 0:
    fresh = prompt_t - cache_read - cache_write
else:
    fresh = prompt_t
```

背景是不同 provider 报的 prompt token 含义不同，Anthropic 报新鲜 token，OpenRouter 和 LiteLLM 报含缓存的总量，这段代码把两种口径都归一成「新鲜」。同一个启发式在两个文件里各实现一次，改一处忘一处就会让 tracing 里的成本和记账里的成本对不上。第 04 章讲记账时提过这个隐患，这里是它的另一半。成本计算本身是尽力而为，价格表不可用时降级成 None 而不是抛错，注释：pricing is best-effort; never break tracing。

## 六、取舍：为什么不做 X

**为什么不用 OpenTelemetry？** 这个决定被一个测试钉住了，文件头写得很清楚：

> Pin the absence of centralized OpenTelemetry tracing / exporter.
> Pico has no OTEL dependency and no `pico/**` module imports opentelemetry.
> Adding an OTEL exporter dependency (or an import) later must break this test so
> the decision is revisited deliberately.

两个断言：`importlib.util.find_spec("opentelemetry")` 必须是 None，也就是环境里装不出这个包；把 `pico` 包目录下所有 `.py` 文件的文本读出来找 opentelemetry 这个词（连注释都算），命中列表必须为空。理由是这层的定位是本地非侵入的审计记录，不是分布式追踪；引入 OTEL 意味着依赖、collector、exporter 配置，而默认导出会把 prompt 和工具输出送出本机。把决定写成测试而不是写成文档，是为了让将来改主意的人必须显式删掉这个测试，也就必须重新讨论一次。要补一个层次，拒绝的是依赖和导出面，不是它的设计纪律：`docs/TRACING_STANDARD_API.md` 自己写明 This mirrors the OpenTelemetry model（library 定 API 和数据模型、应用手动埋点），API 小而慢动，存储和看板在后面自由迭代。面试里被追「你是不是不懂 OTel 才不用」，这一句是答案的下半段。

**为什么不做集中式的观测服务？** 项目状态文档里明确写了不做：本地查看器是运维辅助，不是托管控制平面，也没有独立的可观测性产品计划。

**为什么大载荷不进 span？** 进了 span 文件就没法 grep 了。拆成引用加预览，既保住可读性又不丢完整数据，代价是查完整内容要多跳一步。

**为什么吞异常只记 debug？** 因为观测失败是运维问题不是用户问题。代价是 tracing 静默失效时不容易察觉，缓解手段是有一个专门的测试模拟内部失败并断言业务照常返回。

## 七、一次真实翻车：新门抓到真 bug，也抓到自己

这个故事的三段都值得讲，出自 `3dcc6eb`（fix(spine): keep a turn's trace rooted and its gate status honest）。前置说明：它引入的 V-TE0 门来自 PR #51，晚于教程基线，本节的 `spine.turn`、`root=True` 在基线工作树里都还不存在。

**第一段，门抓到了产品 bug。** V-TE0 定的不变量是一次 turn 恰好一条 trace，链路 `spine.turn` 到 `session.turn` 到叶子（`llm.call` / `tool.call`）。Lane 在提交者的上下文里同步启动 worker（第 01 章讲过这个同步创建 task 的设计，它让 turn 一离开队列就是可取消的）。副作用是：如果一个 turn 是从某个活跃 span 内部提交的（子代理管理器在 `subagent.run` 还没关闭时就宣告结果），这个新 turn 会继承调用者的 trace id，`spine.turn` 挂到了调用者的 span 下。两个 turn 共用一条 trace，抓住它的正是这道门自己的两个检测器（`spine_root_not_a_root`、`duplicate_spine_root`），而且是在真实证据上触发的。修法是给 `trace.span` 加一个 `root=True` 参数，文档一句话：refuses any inherited context: the span always mints a fresh trace and has no parent；`Lane._run_turn` 用它开 `spine.turn`，并配了一个契约测试 `test_root_refuses_inherited_context` 钉住（都晚于基线）。

**第二段，门抓到了自己的判定 bug。** 判定函数 `_result` 原本先看计数器再看发现项，于是出现一类漏判：有些检测器发现的矛盾，恰好落在计数器数不到的记录上（一个没有 outcome 的 `spine.turn`、一条没有对应丢弃记录的投递失败通知）。这类情况被报成 inconclusive 而不是 failed。修后发现项优先于计数，代码注释把理由写死了：reporting that as inconclusive would sell a violated contract as an unexercised one，把违反契约的结果卖成未测过的结果；真正空跑一场仍然读作 inconclusive。

**第三段，规范自己说了谎。** 那份规范声称这道门的场景跑的是真实调度器，实际从来没碰过 Scheduler，跑的是 Lane 和 DeliveryHub；还声称五个场景，实际是六个。修正是把规范第 8 节改成点名 Lane / DeliveryHub、补上缺的场景行、写明 Scheduler 为什么在门外，顺带把 `spine.busy_policy` 标注成「请求的策略」而不是「生效的策略」。规范和实现漂移这件事，在文档密集的项目里是常态，值得在面试里承认。

三段连起来是这一章最好的论证：一道新加的门，第一次跑就同时抓到产品的 bug、自己的 bug 和文档的谎。这比「我们加了监控」有说服力得多。

## 八、缺口：能观察，还没关联

这一层目前最大的问题写在项目状态文档的 P0 阻塞项里：

> Evidence is not correlated end to end. Tracing, usage, Turn outcome, Memory, Tool, Channel delivery, and Evolver artifacts do not yet share one verifier-backed evidence identity.

翻译成排查场景就是：想回答「这次比上次慢在哪」「某类任务的工具失败为什么变多」，现在还得人工把几份数据对起来看，因为 span、用量记账、turn 结果、投递记录各自有各自的身份。架构文档里那句总结说的是同一件事，观测记录不会自动成为发布证据。

V-TE0 门（PR #51 引入、`3dcc6eb` 修正，均晚于基线）是往关联这个方向走的第一步。它的实体是 `scripts/verify_turn_evidence.py`（证据基线 main `b65f962` 读出，603 行），把一个确定性场景（六个 turn，各自被驱动到指定终态）跑进临时证据目录，然后用五个纯函数检查产物：turn 关联（每条 trace 恰好一个根、链路不挂错）、用量 join（每行用量凭 `trace_id` 加 `turn_span_id` 必须落回某个 turn 的 span 集合）、投递 join、终态覆盖、场景投递结果。期望终态直接写死在门里而不是场景里，理由是注释原话：场景悄悄不再产生某个状态时，失败的是门，不是被场景重新定义：

```python
EXPECTED_TERMINALS = {
    "scenario:completed": "completed",
    "scenario:tool_failure": "completed_with_tool_failure",
    "scenario:provider_failure": "provider_failed",
    "scenario:runner_error": "error",
    "scenario:cancelled": "cancelled",
    "scenario:delivery_exhausted": "completed",
}
```

每个检测器还各自用损坏的 fixture 单测过（`tests/test_verify_turn_evidence.py`），不是只对健康数据跑一遍。报告 schema `pico.turn.evidence.v1`，复跑命令 `make verify-turn-evidence`。它证明的是「一次 turn 的证据在 tracing、用量、投递之间自洽」的确定性契约；Issue #23 已由 PR #51 关闭。它仍不是 live 证据，完整发布聚合归 V-R0。

写在这里而不是藏起来，是因为这就是这层的真实成熟度：机制完备（非侵入、结构化、有语义约定、有存储和查看器），关联未完成。

## 九、怎么被验证

`test_tracing_api.py` 21 个用例（`grep -c "^def test_"`，工作树），可以按三组记。行为组：嵌套与 kind 推导、错误标记状态并原样重抛、artifact 引用挂载、剥离内联图片数据的同时不改动活载荷、`read_file` 读 SKILL.md 时 retype 成 skill、invocation_source 在根上是 None 而嵌套时从外层派生。提取器组：tool_call、tool 错误结果标 ERROR、memory_extract、memory_consolidate、personalize、skill_rewrite 的输入输出产物、subagent 子节点嵌套。契约组：`audit.span.v1` 的字段集合冻结（多一个少一个 key 都红）、span kind 词表冻结、标准 span 的必需属性、关闭时是纯直通（断言原函数照常执行且 `trace.current()` 为 None）、内部失败绝不打断宿主（monkeypatch 把 `emit` 换成抛 RuntimeError 的桩，断言业务返回值照旧、业务自己的异常也照旧）。最后两个是「非侵入」这条契约的直接测试。

`test_no_otel_tracing.py` 两个断言钉住不引入 OTEL 这个决定。

跨层的门是 V-TE0（PR #51 落地，晚于基线），报告 schema `pico.turn.evidence.v1`，五个检查函数与场景表见第八节。

## 十、预演追问

**「你们怎么做可观测性的？」**
分三层。最里层是结构化 span，用装饰器给关键方法标一行，函数体不动，全仓 22 处埋点，模型调用、工具执行、记忆六个环节、上下文整理、技能注入与检索、插件加载、子代理各有语义提取器负责填字段，嵌套靠 contextvars 自动完成，跨 asyncio 任务也成立。中间层是存储，JSONL 一行一个 span，大载荷单独落文件，span 上留路径加 SHA1 加字节数的引用和截断预览，日志按跨日或 50 MiB 轮转归档。最外层是本地看板，`pico tracing` 一条命令，Node 实现零 npm 依赖。有条边界我要主动说：这层现在能观察但还不够方便分析，span、用量记账、turn 结果、投递记录各有各的身份，跨层关联是我们列在阻塞项里的未完成工作。

**「加了 tracing 会不会影响性能或稳定性？」**
稳定性上这是一条代码级契约，不是态度。关掉时装饰器直接调原函数、不进上下文；开着时业务异常先记成错误状态再原样重抛，一个字节不改；而 tracing 自己的失败，包括开 span、发出、写产物、三个钩子，全部各自吞掉并只写 debug 日志。这条有专门的测试，用 monkeypatch 让内部环节抛异常，断言业务照常返回。性能上主要开销是每个 span 一次 JSONL 追加，大载荷不进主文件，预览默认截到 500 字符。

**「为什么不用 OpenTelemetry？」**
定位不同。我们要的是本地、非侵入的审计记录，不是分布式追踪；引入 OTEL 意味着依赖、collector 和 exporter 配置，而默认导出会把 prompt 和工具输出送出本机，对一个本地跑的 agent 这是个不划算的交换。这个决定我们写成了测试而不是文档：一个测试断言环境里装不出 opentelemetry 这个包，另一个把 pico 包下所有 Python 文件读出来断言没有任何文件提到这个词。将来要改主意，必须先显式删掉这个测试，也就必须重新讨论一次。同时我们没有拒绝它的设计，标准文档自己写明镜像了 OTel 的模型，库定 API 和数据模型、应用手动埋点，API 小而慢动，存储看板自由迭代。我觉得把架构决定钉成测试，比写在 README 里更不容易腐化。

**「一次运行出问题，你怎么查？」**
按层收敛。先看这次 turn 的结果对象，它带着结构化字段：工具调了几次失败几次、记忆命中几条、上下文走的是快路慢路还是降级、降级原因是什么。这一步能定位到哪一层出问题，不用翻日志。然后进 span，一次运行是一棵树，从 turn 根往下能看到每次模型调用、每个工具执行、上下文整理的耗时和状态，模型调用还自带 invocation_source，能直接看出它是替哪个环节干活的。需要完整的输入输出就顺着 artifact 引用取，路径和哈希都在 span 属性上。上下文那层还有一份逐轮的 JSONL 轨迹，能重建当轮到底选了哪些消息。诚实的部分：跨层关联还没做完，想问「这次比上次慢在哪」这种跨维度问题，目前还要人工把几份数据对起来。

**「你们的观测数据会不会泄露用户内容？」**
三条。第一，全部落在本地，没有任何导出通道，这也是不上 OTEL 的原因之一。第二，落盘前过一次载荷净化，内联的图片 base64 会被正则换成占位符，返回非变异拷贝，有测试同时验证剥离生效且不改动运行中的载荷对象。第三，长内容不进 span 主文件，只留截断预览。要补一个边界：净化针对的是体积和明显的二进制载荷，不是通用的 PII 脱敏，真正做了分级脱敏的是真实平台验证那道门，它有白名单加密钥替换加平台 id 哈希三层。

## 口播稿

> 这一层的定位是本地的、非侵入的审计记录，不是分布式追踪。采纳方式是给关键方法加一行装饰器，函数体不动，全仓 22 处埋点，模型调用、工具、记忆、上下文整理各有一个语义提取器负责填字段，嵌套靠上下文变量自动完成。非侵入对我们是代码级契约不是态度：关掉时直接调原函数不做任何 IO，开着时业务异常先记状态再原样重抛，而 tracing 自己的失败，包括开 span、落盘、写产物和三个钩子，全部各自吞掉只写 debug，有专门的测试模拟内部异常断言业务照常返回。存储是 JSONL，大载荷单独落文件，span 上留路径加哈希的引用和截断预览。我们主动没上 OpenTelemetry，理由是默认导出会把 prompt 和工具输出送出本机，而这个决定被写成了两个测试，将来要改必须先删测试，也就必须重新讨论；分层纪律倒是照着 OTel 的模型做的，API 小而慢动，存储看板自由迭代。这层最真实的成熟度是：机制完备，跨层关联没做完，span、用量、turn 结果、投递记录还没有共享一个证据身份，这是我们列在阻塞项里的活。

## 复习路径（10 分钟）

1. 背非侵入的四条落地：关掉是空对象、业务异常原样抛、内部失败吞成 debug、开 span 本身也不能炸。
2. 讲得出三个钩子的分工，尤其 extract 为什么挂在 finally，checkpoint 为什么用同一个 span id。
3. 记住存储布局四行和四个数：轮转 50 MiB、预览 500 字符、埋点 22 处、用例 21 个；artifact 的 SHA1 是引用不是写入去重。
4. 把不上 OTEL 的理由和「决定写成测试」这个做法讲成一条完整论证，末尾补一句「分层纪律镜像 OTel 模型」。
5. 记牢边界的准确表述：V-TE0（六场景、五检查、损坏 fixture 单测）已完成跨层确定性关联，但不是 live 证据；它晚于代码基线，完整发布聚合归 V-R0。
