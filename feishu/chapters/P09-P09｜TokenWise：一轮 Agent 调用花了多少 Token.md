# P09｜TokenWise：一轮 Agent 调用花了多少 Token

> 小林让 Pico 读配置、运行测试、修改文件。Agent 为了完成这三个动作连续调用模型，每次都要再次发送系统指令、工具定义和已有历史。本章从一条调用记录出发，看 Pico 怎样读取 Provider usage、估算成本，再理解稳定前缀为什么能利用 DeepSeek 的自动缓存。

## 读前准备

这章会直接用到三个概念：

- **Iteration**：Turn 内的一次模型推进；
- **Provider**：把统一模型请求转换成具体厂商调用；
- **Token**：模型计量文本长度的单位，Provider 通常按输入和输出 Token 计费。

本章对应 `origin/main@9914182c7bafa3d3e2a7a5564e792fc9d6d524b7`。代码行为以这份 `main` 为准；DeepSeek 数字来自文中单独标出的冻结实验工件。

## 读完本章，你能回答什么

- 一条 Turn 为什么会产生多次输入成本？
- Provider 返回的缓存 Token 怎样变成一条含义统一、价格未知时仍诚实的记录？
- 75.19% 缓存命中率和 73.44% 成本降幅是怎样测出来的？

## 先看一条六次调用的 Turn

一条代码修复任务可能这样推进：

```text
调用 1：读取配置
调用 2：决定运行哪组测试
调用 3：看到失败，读取相关源码
调用 4：修改文件
调用 5：重新运行测试
调用 6：生成最终回复
```

第 1 次请求带着系统指令、工具定义和用户任务。第 2 次请求还要带上第 1 次的模型消息与工具结果。后面的消息越来越长，但开头那段系统指令和工具定义通常保持不变。

以一次 DeepSeek 调用为例，Provider usage 可能表示：

```text
prompt total  = 12,000
cache hit     = 9,000
cache miss    = 3,000
output        =   600
```

这 12,000 个输入 Token 都参与了模型理解，但价格不一样。命中的 9,000 个 Token 使用缓存命中价，未命中的 3,000 个 Token 使用普通输入价。只保存 `prompt total`，成本就无法按 Provider 规则重建。

## 先认代码：一条 Provider 调用的五站

| 阶段 | 主要文件与符号 | 这一站做什么 |
|-|-|-|
| 1. 准备请求 | `pico/agent/loop/main.py` | 取得本次 messages、tools 和 model |
| 2. 经过调用前 Hook | `pico/token_wise/registry.py` | 把请求交给已注册策略；当前共享 Host 为空操作 |
| 3. 调用并读取 usage | `pico/providers/litellm_provider.py` | 调模型，提取输入、输出和缓存字段 |
| 4. 统一 Token 与价格 | `pico/agent/loop/main.py::_build_usage_snapshot`、`pico/token_wise/pricing.py` | 计算 fresh input 和估算成本 |
| 5. 经过调用后 Hook | `pico/token_wise/registry.py` | 把结果交给已注册策略；当前共享 Host 为空操作 |

这五站和下面的编号一致。当前 CLI、TUI 和 Gateway 的共享组装点没有注入策略，所以第 2、5 站仍会调用 Registry，但里面没有策略可执行。`UsageTracker` 只会出现在显式注入它的实验或测试路径。Model Router 在 Turn 开始前选择模型，等这条调用走完后再单独看。

## 第 1 站：Agent Loop 准备本次真实请求

每次 Iteration 开始时，Agent Loop 已经有一份不断增长的 `messages`，还会从 Tool Registry 取得当前可见的工具定义。

进入 Provider 前，三样东西已经明确：

```text
messages：系统指令、历史、工具结果和当前任务
tools：本次可见的工具 Schema
model：当前调用使用的模型
```

这三样来自当前 Iteration，而不是 Turn 开始时的一份旧快照。工具结果或运行中注入的消息会让下一次调用继续增长。

## 第 2 站：调用前策略按注册顺序处理请求

Agent Loop 把 messages、tools 和 model 交给 `StrategyRegistry.before_llm_call()`。Registry 逐个调用已注册策略，前一个策略的输出会成为后一个策略的输入。

当前共享 Host 的 Registry 为空，三样数据原样进入 Provider。显式安装 `CacheOptimizer` 的实验或测试路径会复制 messages 和 tools，再给本次调用使用的副本加标记；Session 保存的原始消息不受影响。

## 第 3 站：Provider 调用模型并整理 usage 字段

不同 Provider 的 usage 字段名字并不统一。LiteLLM Provider 会提取公共字段：

```text
prompt_tokens
completion_tokens
total_tokens
```

它还会从不同位置寻找缓存字段。DeepSeek 这条路径主要读取：

```text
prompt_cache_hit_tokens  → cache_read_input_tokens
prompt_cache_miss_tokens → cache_miss_input_tokens
```

Anthropic 或 OpenRouter 可能把缓存信息放在另外的字段中。Provider adapter 先做字段映射，Agent Loop 后面就不用直接理解每家 SDK 的对象形状。

## 第 4 站：UsageSnapshot 统一 Token，再估算价格

Provider 世界里，`prompt_tokens` 常见两种含义：

- 有的只报告新输入，缓存读写另外给出；
- 有的报告总输入，其中已经包含缓存读写。

`AgentLoop._build_usage_snapshot()` 会读取 `prompt_tokens`、cache read 和 cache write。当 prompt total 足以包含后两者时，使用：

```text
fresh input = prompt total - cache read - cache write
```

否则保留 Provider 给出的 prompt 值。下游的价格函数和显式安装的 UsageTracker 因而统一读取：

```text
input_tokens       = fresh input
cache_read_tokens  = 缓存读取
cache_write_tokens = 缓存写入
output_tokens      = 模型输出
```

`estimate_cost_usd()` 接收模型名和四类 Token。项目冻结的 miss、hit 和 output 三段价格只匹配非 `openrouter/` 路径，并且去掉可选的 `deepseek/` 前缀后，模型 id 必须是 `deepseek-v4-flash` 或 `deepseek-v4-pro`。`openrouter/...` 模型走 LiteLLM 或 OpenRouter 的普通价格查询。其他模型依次查询 LiteLLM、OpenRouter 和小型 fallback 价格表。

开头那次调用会整理成一个 `UsageSnapshot`。它是 Python `dataclass`，可以理解成把同一条调用的有关字段放进一个对象：

```python
UsageSnapshot(
    model="deepseek/deepseek-v4-flash",
    input_tokens=3000,
    output_tokens=600,
    cache_read_tokens=9000,
    estimated_cost_usd=...,
)
```

第一次看这个对象，只读 `input_tokens`、`cache_read_tokens` 和 `output_tokens`。这里的 `input_tokens` 专门表示本次新计算的输入，也就是 fresh input。

Snapshot 还带着 `session_key`、`trace_id` 和 `turn_span_id`，用来把持久化 usage 行连接回对应 Turn。Tracing 关闭时，两个追踪字段保持 `None`。

## 第 5 站：调用后 Hook 把结果交给已注册策略

Agent Loop 把 Provider response 和 `UsageSnapshot` 交给 `StrategyRegistry.after_llm_call()`。这一阶段观察的是已经完成的调用，适合做 usage 记录和预算统计。

当前共享 Host 没有注册策略，所以这里直接结束。显式安装 `UsageTracker` 的实验或测试路径中，每次调用才会累计到当前 Session、当天和当前进程，并可按配置追加到 `usage-YYYY-MM-DD.jsonl`。

这张图按主线从左往右读。蓝色框表示路由、迭代和 Provider，绿色框是调用前后的策略，灰色框是 usage 与 Trace。橙色提示给出两个容易读错的边界：未知价格保留为空值，配置字段存在也要继续核对 Registry 里实际装了什么。

**图 P09-A｜TokenWise 在一次 Provider 调用前后的真实位置**

![](images/P09/img1.jpg)

Router 每条 Turn 运行一次，Strategy hook 每次 Provider 调用都经过；Registry 为空时不会执行具体策略。Provider 原生缓存位于模型服务内部，Strategy 只处理发出的请求或观察返回结果。

## 当前共享 Runtime 怎样装配策略

`pico/cli/_token_wise_stack.py::install_from_config()` 可以根据配置创建 `CacheOptimizer` 和 `UsageTracker`。`AgentLoop` 也接受 `strategies` 参数，没有传入时会创建空 Registry。

继续读共享组装点 `pico/cli/_runtime_assembly.py::assemble_runtime()`，当前构造 `AgentLoop` 时没有传 `strategies`。所以 CLI、TUI 和 Gateway 共用的 RuntimeAssembly 当前使用空 Registry；独立实验和测试可以显式注入策略。

`CacheOptimizer` 面向接受 `cache_control` 标记的 Provider。它复制 messages 和 tools，再标记 system、工具列表尾部和若干滚动消息位置。DeepSeek 使用服务端自动前缀缓存，不读取这些显式标记。

这两个事实可以同时成立：共享 Runtime 当前没有装配显式策略，DeepSeek 仍会根据请求前缀自动判断缓存命中。

## DeepSeek 自动前缀缓存怎样生效

同一条 Turn 连续调用模型时，开头常有一段稳定内容：

```text
系统指令
→ 工具定义
→ 较早的会话历史
→ 新追加的 assistant/tool 消息
```

前面字节保持一致时，DeepSeek 可以把已经处理过的前缀报告为 cache hit。每次调用都改动系统指令或 Tool Schema 的开头，公共前缀会缩短，命中率也会下降。

Pico 在这条路径上做四件事：保持普通请求前缀稳定；读取 hit/miss usage；按模型专属价格估算成本；把原始 Trial、Verifier 和报告摘要绑定起来。

## 配对实验怎样只改变前缀稳定性

冻结实验使用 4 类任务，每类 3 个 case、3 次 repetition。一共形成 36 个配对区组，每个区组运行两臂：

| 实验臂 | 请求行为 | 用途 |
|-|-|-|
| `prefix_stable` | 保持 Pico 普通请求的稳定前缀 | treatment |
| `prefix_disrupted` | 每次调用故意改动开头的 system 和 Tool Schema 字节 | 负向反事实 |

两臂共享同一任务、模型、预算、Tool set 和 Verifier，也都使用 DeepSeek 自动缓存。每个 Trial 使用独立 `user_id`，避免一臂预热另一臂。

四类工作负载分别是：

| 工作负载 | 每个 Trial 做什么 |
|-|-|
| `stable_dialogue` | 6 条短 Turn，不调用工具 |
| `long_history` | 先种入 16 条历史 Turn，再执行 6 条 Turn |
| `tool_accumulation` | 6 条 Turn，每条有 1 次验收过的工具调用 |
| `intra_turn_tool_chain` | 1 条 Turn 内完成 3 步工具链 |

总量是 36 个配对区组、72 个 Trial、504 次真实 Provider 调用。

下面这张图先读左上角的冻结条件，再看中间的一对一比较。右侧是最终指标，底部是从 raw Trial 到 report digest 的证据链。

**图 P09-B｜DeepSeek 稳定前缀与扰动反事实的配对实验**

![](images/P09/img2.jpg)

扰动臂只用于建立实验反事实，产品运行采用普通稳定前缀。实验回答的是：其他条件固定时，前缀稳定性会怎样影响 DeepSeek 自动缓存与估算成本。

## 实验指标怎样计算

保守缓存命中率是：

```text
cache_read / (cache_miss + cache_read)
```

单位验收成功任务的估算成本是：

```text
全部有效 Trial 的估算成本之和 / verified successes
```

失败 Trial 的成本仍留在分子里。这样任务提前失败不会因为调用次数少而得到一个虚低成本。

正向结论需要同时通过这些 Gate：

- 36 个计划区组都有效；
- usage 满足 prompt 与 hit/miss 的守恒关系；
- 实际服务模型与冻结模型一致；
- 四类工作负载齐全；
- treatment 任务通过率没有下降；
- 稳定前缀同时改善命中率和成本；
- 没有 fallback、模型漂移或 usage 缺失。

## 冻结结果怎样读

实验模型是 `deepseek/deepseek-v4-flash`。先看冻结报告给出的证据判定：

```text
ship_complete=true
measurement_valid=true
positive_claim_eligible=true
claim.claim_eligible=true
claim.findings=[]
```

也就是说，计划内工件完整、测量有效，而且这条正向结论通过了声明 Gate。接着再读具体数字：

| 指标 | `prefix_disrupted` | `prefix_stable` |
|-|-|-|
| Valid Trials | 36 | 36 |
| Verified task pass rate | 100% | 100% |
| 保守缓存命中率 | 0% | 75.19% |
| 估算成本 / verified success | \$0.008694 | \$0.002309 |

稳定前缀相对扰动反事实的单位验收成功任务估算成本降低 73.44%。四类 workload 齐全，fallback、模型漂移、usage incomplete 和 task failure 都是 0。

冻结证据身份包括：

```text
source commit: 31ed829b0cb36f1a5e7811d71004db1b15958f40
plan digest:   92d7f5c7625d4c961286c7e64094672ab6986915c96c6dadbc36319779ce97cd
corpus digest: 5942ba349bd76438ea4a87508680c05059589400c2ffbf1b62a5db443dd407b2
report digest: fcde99b98c8bc46d0852015d7a92c01a0de6a4e4216f773045375f2f06e75aec
```

这组数字只对应冻结的四类工作负载、指定模型、指定价格快照和这条配对轴。`$0.002309` 是重建的 API 估算成本，没有与 Provider 发票对账；73.44% 也不表示逻辑输入 Token 减少了同样比例。

## Model Router 位于 Turn 开始处

配置了 Router 时，Agent Loop 在一条 Turn 真正开始前调用 `select_model_chain(content)`。返回值包括一个主模型和一组候选模型：

```text
primary = model_A
fallback = [model_B, default]
```

普通 Router 根据任务分类和 benchmark profile 选模型。KNN Router 会检索相似历史任务，用 reward、cost、邻居数量、最小相似度和 margin 决定是否离开默认模型。数据加载、embedding 或分类失败时，Router 返回空选择，继续使用配置默认模型。

路由不会改变 `session_key`、conversation 或历史归属。真实 Runtime 可以为可用性准备 fallback；严格单模型实验会把 fallback 当成模型漂移，让对应区组失效。

Router 和 TokenStrategy 都能接触 model，但时机不同。Router 先为整条 Turn 选择主模型与候选链，Strategy 在每一次实际 Provider 调用前按注册顺序运行。

## UsageTracker 的持久化边界

JSONL 里的成本来自本地价格元数据与 Provider usage。写文件失败时，Tracker 记录 warning 并丢弃当前 buffer，模型回答继续返回。正式报告需要检查 usage 是否完整，缺少的行不能按零成本处理。

## 失败和降级怎样收口

| 情况 | 当前行为 | 读数时怎样处理 |
|-|-|-|
| before hook 抛错 | 中止 Provider 调用 | 暴露策略错误 |
| after hook 抛错 | 记录 warning，保留模型回答 | 标记可能存在遥测缺口 |
| 模型不接受 `cache_control` | CacheOptimizer 原样透传 | 不生成显式 breakpoint |
| 模型价格未知 | `estimated_cost_usd=None` | 不进入美元结论 |
| DeepSeek usage 缺 hit/miss | 保留已观察字段 | 严格实验让 Trial 失效 |
| Router 失败或置信不足 | 使用默认模型 | Session identity 保持不变 |
| Provider 使用 fallback | Runtime 继续尝试候选模型 | 单模型实验判为模型漂移 |
| Turn 在响应前取消 | 没有完整 Snapshot | 不补成零成本调用 |

取消发生在 Provider 已经返回以后，则按实际观察到的 usage 记账。取消本身没有单独的 TokenWise 生命周期。

其中三条容易被误读：

- Provider 没返回 cache miss 时，代码不会根据请求长度补出猜测值；
- `None` 表示当前无法估算，`0.0` 只表示已知价格算出的真实零成本。UsageTracker 聚合多次调用时，只要其中一次价格未知，聚合成本也保持 `None`，Token 数仍正常累加；
- TUI 复用同一个 usage 容器。新一次调用价格未知时，Agent Loop 会删除上一轮残留的 `cost_usd`，避免界面继续显示旧价格。

## 走完以后，再整理术语

| 日常理解 | 代码名 | 作用范围 |
|-|-|-|
| 一次模型调用的统一账单行 | `UsageSnapshot` | fresh input、缓存、输出和估算成本 |
| 调用前后的策略接口 | `TokenStrategy` | 改写请求或观察结果 |
| 有序策略列表 | `StrategyRegistry` | 固定 hook 顺序和错误语义 |
| 显式缓存标记策略 | `CacheOptimizer` | 为支持 `cache_control` 的 Provider 标记位置 |
| usage 记录器 | `UsageTracker` | Session、每日、进程累计与 JSONL |
| 服务端自动缓存 | DeepSeek prefix cache | 根据稳定请求前缀产生 hit/miss |
| Turn 级选模 | Model Router | 选择主模型和候选模型 |
| 单位成功任务成本 | cost / verified success | 把任务验收放进成本分母 |

## 从哪些文件开始读

| 顺序 | 文件与符号 | 只看什么 |
|-|-|-|
| 1 | `pico/token_wise/base.py::UsageSnapshot` | fresh input 和未知价格语义 |
| 2 | `pico/agent/loop/main.py::_build_usage_snapshot` | Provider usage 怎样统一 |
| 3 | `pico/token_wise/pricing.py::estimate_cost_usd` | 价格查找和 `None` 返回 |
| 4 | `pico/token_wise/registry.py::StrategyRegistry` | hook 顺序与异常边界 |
| 5 | `pico/providers/litellm_provider.py` | DeepSeek hit/miss 字段映射 |
| 6 | `pico/cli/_runtime_assembly.py::assemble_runtime` | 当前共享 Host 实际传了什么 |
| 7 | `pico/routing/knn_router.py::KNNModelRouter.select_model_chain` | 低置信时怎样留在默认模型 |

实验设计和结果读取 `docs/evaluation/tokenwise-cost.md`。源码锚点使用符号名，不依赖旧行号。

## 用测试验证理解

| 想验证什么 | 先读哪个测试 |
|-|-|
| 策略顺序与前后 hook 异常 | `tests/test_token_wise_registry.py` |
| 缓存标记不污染原始消息 | `tests/test_token_wise_cache_optimizer.py` |
| 未知价格怎样进入聚合 | `tests/test_token_wise_usage_tracker.py` |
| Provider-aware 价格计算 | `tests/test_token_wise_pricing.py` |
| Agent Loop 的策略 seam | `tests/test_token_wise_agentloop_experiment.py` |
| 配对 Trial、reducer 和 Claim Gate | `tests/test_picobench_tokenwise_cost.py` |
| 付费 campaign 的预算与授权边界 | `tests/test_picobench_tokenwise_cost_campaign.py` |
| KNN 低置信回退 | `tests/test_knn_router.py`、`tests/test_routing_fallback_chain.py` |

这些测试可以验证代码合同和冻结工件的离线重建。它们不会再次发起 504 次真实 Provider 调用。

## 25 分钟代码练习

目标：从一份 Provider usage 手算并追踪一条 `UsageSnapshot`。

给定：

```text
prompt_tokens = 12,000
cache_read_input_tokens = 9,000
cache_creation_input_tokens = 0
completion_tokens = 600
```

1. 第 1 站，在 `_run_agent_loop()` 找到 messages、tools 和 model；
2. 第 2 站，找到 `before_llm_call()`；
3. 第 3 站，在 Provider adapter 找到 DeepSeek hit/miss 映射；
4. 第 4 站，手算 fresh input，并在 `_build_usage_snapshot()` 找到相同分支；
5. 找到 `estimate_cost_usd()` 的参数顺序和 unknown model 返回 `None` 的分支；
6. 第 5 站，沿 `after_llm_call()` 确认空 Registry 怎样直接返回，再到显式注入路径查看 `UsageTracker._add_into()`；
7. 解释一次未知价格为什么会让聚合成本保持未知；
8. 再到 RuntimeAssembly 确认当前共享 Host 的 Registry 怎样创建。

完成后回答：

- `prompt_tokens` 与 `UsageSnapshot.input_tokens` 什么时候不同？
- 75.19% 和 73.44% 分别衡量什么？
- 为什么 Router fallback 在产品运行中可用，在单模型实验中会让区组失效？

## 本章复盘

- [ ] 能解释一条 Turn 为什么产生多次输入成本；

- [ ] 知道 DeepSeek hit/miss 字段怎样进入 Provider usage；

- [ ] 知道 `UsageSnapshot.input_tokens` 表示 fresh input；

- [ ] 能区分 `None` 与 `0.0` 成本；

- [ ] 能解释 before hook 和 after hook 的错误边界；

- [ ] 知道当前共享 RuntimeAssembly 使用空 StrategyRegistry；

- [ ] 能区分 CacheOptimizer 与 DeepSeek 自动前缀缓存；

- [ ] 能复述 4 类任务、36 个区组、72 个 Trial 和 504 次调用；

- [ ] 会把 75.19%、$0.008694、$0.002309、73.44% 与两臂 100% 通过率一起陈述；

- [ ] 知道扰动臂是实验反事实；

- [ ] 不会把估算成本写成 Provider 实际账单；

- [ ] 能解释 Router 与 TokenStrategy 的运行时机。

## 接下来怎么读

- [P10｜Tracing 与终态](https://icnoljnkix43.feishu.cn/wiki/OS4WwBltmi3v5gkfmQ8cPVmOnec)：usage、模型调用和 Delivery 怎样连接到同一条 Turn；
- [P11｜PicoBench 与证据 Gate](https://icnoljnkix43.feishu.cn/wiki/XTOEwv9vhig1IikThC8cOJXEnrg)：冻结任务、Verifier 和报告摘要怎样约束数字；
- [面试总话术](https://icnoljnkix43.feishu.cn/wiki/H9rewOY10ixocdkYCuwcIHqjneY)：准备项目表达时，再进入逐字话术线。
