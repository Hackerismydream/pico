# P10｜Tracing 与终态：答案生成了，任务就成功了吗

> 小林让 Pico 查构建失败并把结论发到群里。Agent 生成了完整回答，飞书发送却被平台拒绝。只保存最终文字时，这次请求看起来像成功；Tracing 会把执行和投递分别记录下来。

## 读前准备

这章只需要先认识三个词：

- **Turn**：Pico 对一条请求做出的完整反应；
- **Trace**：一条 Turn 经过各模块时留下的关联记录；
- **Span**：Trace 里的一个步骤，比如一次模型调用或一次渠道发送。

本章对应 `origin/main@9914182c7bafa3d3e2a7a5564e792fc9d6d524b7`。终态名称、Span 父子关系、渠道发送关联和大内容保存方式都以这份 `main` 源码为准。

## 读完本章，你能回答什么

- 一条 Turn 的模型、工具、Session 和发送记录怎样连成同一棵树？
- Agent 执行结果与消息投递结果为什么要分别记录？
- 用户说“没有收到”时，怎样沿 Trace 找到真正失败的步骤？

## 先看一次“有答案但没送达”的请求

小林发来任务：

> 查一下今天构建为什么失败，然后把结论发到群里。

实际执行过程可能是：

```text
模型请求 web_fetch
→ 工具网络超时，返回 failed=True
→ 模型改用已有日志，生成保守结论
→ Agent Loop 正常结束
→ 飞书 SDK 拒绝消息
→ 用户没有收到回复
```

这条链里有四种不同事实：工具调用失败过，模型仍然给出回答，Turn 正常收束，消息投递失败。Tracing 把它们分别写进对应 Span，最后形成：

```text
Turn outcome     = completed_with_tool_failure
Delivery outcome = dropped
```

最终文本只说明模型写了什么。终态回答这一轮怎样结束，Delivery outcome 回答终端内容有没有送达。

## 先认代码：一条 Trace 的五站

| 阶段 | 主要文件 | 这一站留下什么 |
|-|-|-|
| 1. 打开 Turn 根节点 | `pico/spine/scheduler.py` | `spine.turn` 与 conversation identity |
| 2. 记录 Agent 工作 | `pico/agent/loop/main.py` | `session.turn`、模型、工具和 usage |
| 3. 传播关联信息 | `pico/tracing/context.py`、`trace.py` | trace id、parent span id 和 Span 生命周期 |
| 4. 关联渠道发送 | `pico/spine/delivery.py` | `channel.deliver`、尝试次数和投递结果 |
| 5. 持久化证据 | `pico/tracing/store.py` | Span JSONL 与独立 artifact 文件 |

接下来继续用小林这条请求，按五站走完正常记录路径。终态分类和异常分支放在后面。

## 第 1 站：Scheduler 为每条 Turn 打开独立根节点

conversation Lane 真正开始执行请求时，`Lane._run_turn()` 打开：

```text
spine.turn
```

这个 Span 带着 conversation id、来源、渠道和 busy policy。它使用 `root=True`，每条 Turn 都会创建新的 trace id，也没有父节点。

根节点放在 Scheduler 这一层，因为 Lane 同时看得到：

- Turn 是否已经发出 `TurnStarted`；
- Runner 正常返回、抛错还是收到取消；
- 最终应发 `TurnEnded` 还是 `TurnFailed`。

Agent Loop 负责完成任务，Scheduler 负责 Turn 的生命周期终态。Subagent 结果回注为新 Turn 时，也会得到新的根 Trace，不会挂在提交它的旧 Turn 下面。

## 第 2 站：Agent Loop 在根节点下面记录真实工作

Runner 进入 Agent Loop 后，`AgentLoop.run_turn()` 打开 `session.turn`。后续模型和工具调用成为它的子节点：

```text
spine.turn
└── session.turn
    ├── llm.call
    ├── tool.call
    └── llm.call
```

第一次看这些 Span，只读两个字段：`name` 表示发生了什么，`parentSpanId` 表示它挂在哪一步下面。

Provider 调用会留下 model、usage 和输入输出引用。工具调用会留下 tool name、`tool_call_id`、是否失败和结果引用。Memory、Skill 和 Subagent 也使用各自的 Span 名称。

开头的 `web_fetch` 超时会写进 `tool.call`，并让 Agent Loop 的 `tool_failures` 增加。第二次 `llm.call` 仍可生成回复，所以工具失败不会自动把整条 Turn 改成 Runtime error。

## 第 3 站：普通异步调用沿 Context 传播

Tracing 把当前 `trace_id` 和 `parent_span_id` 放进 `ContextVar`。普通函数继续 `await`，或者在当前上下文中创建短生命周期子 Task 时，新 Span 会继承正确父节点。

`trace.span()` 负责打开和关闭 Span：

```python
with trace.span("tool.call", attributes) as span:
    result = await tool.execute(...)
```

业务函数抛出的异常会先被 Span 标成错误，再原样向外传播。Tracing 自己打开、写入或关闭失败时，内部会吞掉观测异常，业务调用继续按原结果运行。

这种传播适合跟着调用栈走的工作。常驻 worker 会持续处理很多 Turn，需要下一站的显式关联方式。

## 第 4 站：Delivery worker 取出消息时重新接回原 Trace

每个 Outlet worker 都是长驻 Task。它创建时只会获得当时的 Context，之后可能连续发送很多 Turn 的消息。若直接沿用 worker 自己的 Context，后来的发送记录会挂到错误请求下面。

DeliveryHub 在正文入队时，把当前关联信息一起放进 `_Routed`：

```text
deliverable
trace_id
parent_span_id
```

worker 取出队列项后，先调用 `trace.attach(trace_id, parent_span_id)`，再打开 `channel.deliver`。这样发送可以晚于 Turn 结束，却仍然回到原 Trace。

下面这张图先读左半边的 `spine.turn → session.turn → llm.call/tool.call`，再读右半边的常驻 Outlet worker。底部展示 Span JSONL 与大 artifact 的分离方式。

**图 P10-A｜一条 Turn 的 Trace 怎样跨过 Agent Loop 和常驻 Delivery worker**

![](images/P10/img1.jpg)

普通异步调用靠 ContextVar 继承，跨长寿命队列时由队列元素携带关联 identity。图中两条路径最终使用同一个 trace id。

## 第 5 站：Span 和大内容分开保存

`TraceStore` 在 state directory 下保存：

```text
logs/audit-events.log
logs/audit-spans.log
logs/audit-artifacts/...
logs/archive/<date>/...
```

每个 Span 是一行 JSONL，保存名称、父子关系、状态、少量 attributes 和 preview。完整 Prompt、Tool Result 或模型输出可能很大，`Span.artifact()` 会把它们写进独立文件，Span 只保留路径、字节数和 SHA-1 摘要。

当前 SHA-1 会被写进 artifact 引用和文件名，用来记录内容身份；读取路径没有再次计算哈希做完整性回验。artifact 文件名还带着时间戳，同一 payload 多次写入会形成多个文件，存储层当前没有按摘要复用旧文件。

长 Turn 可以调用 `Span.checkpoint()` 提前写一条 in-progress 记录，最终关闭时再用同一个 span id 写完整记录。离线读取按 `(trace_id, span_id)` 保留最后一条，才能得到最终状态。

TraceStore 采用本地追加写法，方便调试和离线 Verifier。Tracing 写失败不会改写业务结果，所以正式证据仍要检查记录是否齐全。

## Scheduler 怎样决定五种 Turn 终态

`pico/tracing/semconv.py` 冻结了五个互斥值：

| Turn outcome | 触发路径 | 怎样理解 |
|-|-|-|
| `completed` | Runner 正常返回，工具失败数为 0 | 执行干净收束 |
| `completed_with_tool_failure` | Runner 正常返回，工具失败数大于 0 | Agent 带着工具失败收束 |
| `provider_failed` | Runner 抛 `ProviderTurnError` | 模型服务路径失败 |
| `error` | Runner 抛其他执行异常 | Runtime 或 Runner 异常 |
| `cancelled` | Lane 捕获 `CancelledError` | 用户或关闭流程取消 |

前两种对应 `TurnEnded`。后三种对应 `TurnFailed`，并把根 Span 标成 ERROR。

Provider failure 通过异常类别识别。`ProviderTurnError.category` 可以继续保存限流、鉴权或网络等 Provider 分类；终态不会从错误文本内容里猜。

工具单次失败保存在 `tool.call`，Turn 能否收束由 Runner 的真实退出路径决定。Session 保存失败等执行异常会进入 `error`，不会混进 Provider 失败桶。

## Delivery 有自己的三种结果

当一个可投递的 `Text` 或 `MediaOut` 经过 Outlet 后，`channel.deliver` 记录：

| Delivery outcome | 含义 |
|-|-|
| `delivered` | Outlet 在允许的尝试次数内正常返回 |
| `dropped` | 终止错误或重试耗尽 |
| `no_outlet` | `source.channel` 没有注册发送出口 |

飞书 SDK 返回业务拒绝时，Feishu adapter 抛出 `TerminalDeliveryError`，DeliveryHub 记录 `dropped`。Hub 支持通过显式 failure sink 发出 `DELIVERY_FAILED` Notice；当前 `build_gateway()` 没有装配该回调，V-TE0 确定性场景会显式传入它来验证 Notice 与 Trace 的关联。原 Turn 的 `completed` 或 `completed_with_tool_failure` 保持不变。

这张矩阵先读横轴的五种 Turn outcome，再读纵轴的三种 Delivery outcome。带星号的格子最常用：执行干净且送达、带工具失败收束且送达、执行完成但投递失败、执行完成但没有出口。

**图 P10-B｜Turn 执行终态与 Delivery 投递结果的二维矩阵**

![](images/P10/img2.jpg)

`completed + dropped` 表示答案已经生成，但用户没有收到。`completed_with_tool_failure + delivered` 表示工具调用失败过，Agent 给出的回复成功送达。执行失败或取消时，只有形成可投递终端内容才会出现 `channel.deliver`，矩阵里的每个理论组合不会在每条 Turn 上强制生成。

## 沿 Trace 还原开头那次请求

小林那条请求最终可以读成：

```text
spine.turn
  outcome = completed_with_tool_failure
  tool_calls = 1
  tool_failures = 1

session.turn
├── llm.call       模型请求 web_fetch
├── tool.call      failed = true，网络超时
└── llm.call       模型生成保守结论

channel.deliver
  outcome = dropped
  attempts = 1
  error = TerminalDeliveryError
```

这份记录能回答三个不同问题：模型有没有生成正文，工具有没有失败，渠道有没有把正文送到用户。任务是否满足用户验收条件，还需要任务 Verifier 继续判断。

## Tracing 关闭或写失败时怎样处理

Tracing API 把观测错误和业务错误分开：

| 情况 | Tracing 行为 | 业务结果 |
|-|-|-|
| tracing disabled | 返回 `_NoopSpan`，不做 I/O | 保持原执行路径 |
| Span 打开或 emit 失败 | 记录内部 debug 信息 | 业务继续 |
| artifact 写入失败 | Span 保留其他 attributes | 可审计材料变少 |
| 业务函数抛异常 | Span 标成 ERROR | 原异常继续传播 |
| `CancelledError` | Span 标错并向外抛 | Lane 负责取消终态 |
| checkpoint 后进程崩溃 | 只留下 in-progress 与部分子 Span | 证据判为不完整 |

这份选择保证观测模块不会成为 Agent 的单点故障，也意味着 `tracing enabled` 不能直接推出证据完整。

## V-TE0 怎样验证终态和关联合同

`scripts/verify_turn_evidence.py` 定义确定性 Gate `V-TE0`。场景会制造：

```text
scenario:completed          → completed
scenario:tool_failure       → completed_with_tool_failure
scenario:provider_failure   → provider_failed
scenario:runner_error       → error
scenario:cancelled          → cancelled
scenario:delivery_exhausted → completed + dropped
```

Verifier 从原始 Span、usage 行和 Delivery Notice 重建证据，检查：

- 每个 Trace 恰好有一个 `spine.turn` 根；
- `session.turn` 正确挂到根节点；
- `llm.call` 和 `tool.call` 挂到对应 Session；
- usage 行能连接到同一 Turn 的 Span；
- 五种终态都有不同 witness；
- dropped Delivery 有对应失败 Notice；
- checkpoint 去重后保留最终记录。

V-TE0 验证的是确定性分类与关联合同，报告中的 `positive_claim_eligible` 为 N/A。它不输出线上成功率，也不测真实 Provider 的稳定性。

## 用户说“没收到”时怎样查

按这条顺序可以避免无意义地重跑模型：

1. 用 conversation 或 Session 找到 `spine.turn`；
2. 读取 `spine.outcome`；
3. 若 Turn 已完成，查同 trace 的 `channel.deliver`；
4. `dropped` 时看 attempts、retries、error 和平台日志；
5. `no_outlet` 时查 `Source.channel` 与 Outlet 注册；
6. `provider_failed` 时再进入 Provider 调用与错误分类；
7. 有工具失败时展开对应 `tool.call` 和 artifact。

只按时间戳拼接并发请求很容易串线。Trace 关联使用 `trace_id`、`span_id`、conversation 和调用 id。

## 走完以后，再整理术语

| 日常理解 | 代码名 | 负责什么 |
|-|-|-|
| 一条请求的关联记录 | Trace | 把同一 Turn 的步骤连起来 |
| 一个被记录的步骤 | Span | 保存父子关系、状态和少量属性 |
| Turn 根节点 | `spine.turn` | 记录生命周期终态 |
| Agent 工作节点 | `session.turn` | 承接模型、工具、Memory 和 Skill |
| 渠道发送节点 | `channel.deliver` | 记录投递尝试与结果 |
| 大内容文件 | artifact | 保存完整 Prompt、结果或输出 |
| 执行终态 | Turn outcome | completed、provider_failed 等五类结果 |
| 投递结果 | Delivery outcome | delivered、dropped、no_outlet |

## 从哪些文件开始读

| 顺序 | 文件与符号 | 只看什么 |
|-|-|-|
| 1 | `pico/spine/scheduler.py::Lane._run_turn` | 根 Span 和终态写入点 |
| 2 | `pico/tracing/semconv.py::spine_turn_ended` | 工具失败怎样影响 completion 分类 |
| 3 | `pico/tracing/trace.py::span` | Span 怎样继承或创建 Trace |
| 4 | `pico/spine/delivery.py::DeliveryHub._deliver_routed` | worker 怎样 attach 并写投递结果 |
| 5 | `pico/tracing/store.py::TraceStore.persist_artifact` | SHA-1、文件名和引用字段 |
| 6 | `scripts/verify_turn_evidence.py::check_terminal_states` | Verifier 怎样检查终态 witness |

源码锚点使用符号名。代码移动后可以重新搜索，不需要保存旧行号。

## 用测试验证理解

| 想验证什么 | 先读哪个测试 |
|-|-|
| Span 父子关系、Context 与错误隔离 | `tests/test_tracing_api.py` |
| tracing disabled 的 no-op 行为 | `tests/test_no_otel_tracing.py` |
| 五种 Turn 终态与 Trace 根 | `tests/test_turn_evidence_correlation.py` |
| 确定性场景怎样产生 witness | `tests/test_turn_evidence_scenario.py` |
| 损坏工件能否被发现 | `tests/test_verify_turn_evidence.py` |
| Delivery attach、重试和 outcome | `tests/test_spine_delivery.py` |

这些测试验证本地记录与关联合同。真实线上流量、跨机器 Trace 和日志保留策略需要单独验证。

## 25 分钟代码练习

目标：追完一条 `completed + dropped` 的 Trace。

1. 从 `Lane._run_turn()` 找到 `spine.turn`；
2. 找到 `root=True`，解释它怎样隔离新 Turn；
3. 找到 Runner 正常返回后调用的 `spine_turn_ended()`；
4. 在 DeliveryHub 找到 `_Routed` 保存的两个关联字段；
5. 找到 worker 中的 `trace.attach()`；
6. 找到 `channel_deliver()` 写 attempts、retries 和 outcome；
7. 对照 V-TE0 的 `scenario:delivery_exhausted` 检查两个结果轴。

建议边读边填：

```text
Span name | parent | 关键属性 | 谁写入 | 何时结束
```

完成后回答：

- 为什么 `spine.turn` 要在 Scheduler 中打开？
- 常驻 Outlet worker 为什么不能直接沿用自己的 Context？
- `completed + dropped` 应该先排查 Agent 还是渠道发送？

## 本章复盘

- [ ] 能画出 `spine.turn → session.turn → llm.call/tool.call`；

- [ ] 知道每条 Turn 使用独立根 Trace；

- [ ] 能解释 ContextVar 和 `trace.attach()` 的使用边界；

- [ ] 能列出五种 Turn outcome；

- [ ] 能列出三种 Delivery outcome；

- [ ] 能解释 `completed_with_tool_failure`；

- [ ] 能解释 `completed + dropped`；

- [ ] 知道 tracing 写失败不会改写业务结果；

- [ ] 知道 checkpoint 记录按 span id 保留最后一条；

- [ ] 知道 SHA-1 当前记录 artifact 内容身份，读取路径未回验，存储层也不按摘要去重；

- [ ] 知道 V-TE0 验证确定性合同，不代表线上成功率。

## 接下来怎么读

- [P11｜PicoBench 与证据 Gate](https://icnoljnkix43.feishu.cn/wiki/XTOEwv9vhig1IikThC8cOJXEnrg)：原始 Trace、usage 和 Verifier 怎样组成可引用结论；
- [P12｜Evolver](https://icnoljnkix43.feishu.cn/wiki/Ei3Swl1X8ilP50kgDXhcz95En7f)：候选改动怎样经过证据与人工激活；
- [面试总话术](https://icnoljnkix43.feishu.cn/wiki/H9rewOY10ixocdkYCuwcIHqjneY)：准备项目表达时，再进入逐字话术线。
