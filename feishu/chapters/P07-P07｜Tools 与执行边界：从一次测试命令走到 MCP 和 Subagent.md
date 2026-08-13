# P07｜Tools 与执行边界：从一次测试命令走到 MCP 和 Subagent

小林在飞书里发来一条请求：

> 帮我只读检查 Tool Registry 的 timeout 测试为什么失败。需要时查依赖文档，storage 那组问题可以单独调查，最后把证据汇总给我。

这一章先跟着最普通的一步走完：模型提出 `exec`，Pico 校验参数，在选定的执行环境里运行测试，再把结果交回模型。走完这条主线后，我们再把远端 MCP 工具和后台 Subagent 接进来。读到结尾时，你应该能从最终回复往回找到每一次动作的参数、执行位置和失败状态。

本章只回答三个问题：

1. 一次工具调用从模型输出到下一次模型输入，会经过哪些站？
2. 参数校验、超时、执行环境和失败标记分别由谁负责？
3. MCP 与 Subagent 怎样复用这条链路，同时保留自己的边界？

## 开始前只记三个词

- **Tool**：Agent 可以请求的一项动作，例如读文件或运行命令。
- **Executor**：真正执行命令的环境，可以是宿主机，也可以是 microVM。
- **ToolResult**：工具交回的字符串结果，同时带有明确的 `failed` 状态。

你只需要先读过 P03 的 Agent Loop：模型可以在一次 Turn 里多次调用工具。JSON Schema、MCP transport 和 Subagent 的细节会在它们第一次出现时解释。

源码基线是 Pico `origin/main` 的 `9914182c7bafa3d3e2a7a5564e792fc9d6d524b7`。本章描述的是该提交的当前装配行为。

## 先认路：这条请求会经过七站

第一遍不必打开所有类。先把“谁把动作交给谁”连起来。

| 站点 | 文件 | 在这条请求里做什么 |
|-|-|-|
| 1. 接住动作 | `pico/agent/loop/main.py` | 从模型回复中取出 `exec` 请求 |
| 2. 校验动作 | `pico/agent/tools/registry.py` | 找工具、转换参数、检查 Schema、控制超时 |
| 3. 选择执行环境 | `pico/sandbox/__init__.py` | 根据配置构造 Direct 或 BoxLite Executor |
| 4. 收回结果 | `pico/security/trust.py` | 给测试输出加不可信数据围栏，再交回模型 |
| 5. 接入远端工具 | `pico/agent/tools/mcp.py` | 把 MCP Server 的工具包装进同一合同 |
| 6. 缩小可见目录 | `pico/agent/tools/tool_search.py` | 工具很多时，让模型先搜索再调用 |
| 7. 运行子任务 | `pico/agent/subagent/manager.py` | 限额运行独立调查，并把结果送回原会话 |

前四站构成一条完整的普通工具主线。第五至第七站是在同一条请求里按需展开的分支。

## 1. 接住动作：模型先给出请求

模型不会直接拿到 Python 工具对象。它返回一个带名字、参数和调用 ID 的工具请求，例如：

```json
{
  "id": "call_7f2a",
  "name": "exec",
  "arguments": {
    "command": "uv run pytest tests/test_tool_registry_timeout.py -x",
    "timeout": "120"
  }
}
```

这里先看三个字段：

- `id` 把这次请求和稍后的结果配成一对；
- `name` 指向 Registry 里的工具；
- `arguments` 仍然只是模型给出的数据，尚未执行。

`AgentLoop._run_agent_loop()` 发现工具请求后，先把 assistant 消息和请求写入本轮消息列表，再发出开始阶段的 `ToolEvent`。事件里的调用 ID 让 TUI 和 Trace 能追踪同一动作。随后 Agent Loop 把名字和参数交给 `ToolRegistry.execute()`。

同一条模型回复里的多个工具调用当前会依次执行。并行调查由后文的 SubagentManager 管理，普通工具分发本身没有悄悄改变顺序。

## 2. 校验动作：Registry 决定能否执行

`ToolRegistry` 是普通工具的统一分发入口。它按固定顺序处理小林这次 `exec`：

1. 用名字查找已经注册的工具；
2. 按工具 Schema 做有限的安全类型转换；
3. 检查必填项、类型、枚举和数值边界；
4. 在工具声明的超时或 Registry 硬上限内调用工具；
5. 把结果收束成带 `failed` 状态的 `ToolResult`。

上例中的 `"120"` 可以按整数 Schema 转成 `120`。如果模型传来 `"two minutes"`，转换和校验会在业务代码运行前拒绝它。缺少 `command`、工具名不存在、参数越界、调用超时或工具抛出异常，也会得到 `ToolResult(failed=True)`。

这类显式失败会回到模型。模型可以修正参数、改用别的工具，或向小林说明限制。一次工具失败因此可以发生在仍然完成回复的 Turn 里，Trace 会保留 `completed_with_tool_failure`，不会把这次调用涂成干净成功。

普通工具默认受 Registry 的硬上限保护。`ask_user` 一类有意等待人的工具可以声明 `blocking_interaction=True`，由自己的交互协议结束等待。这个例外只改变计时方式，不绕开参数合同和失败状态。

## 3. 选择执行环境：命令到底在哪里跑

`exec` 通过当前 `SandboxExecutor` 执行命令。`build_executor()` 根据配置选择后端：

| 后端 | 命令运行位置 | Workspace | 初始化失败时的行为 |
|-|-|-|-|
| `DirectExecutor` | Pico 所在的宿主进程环境 | 直接使用宿主路径 | 返回宿主执行器 |
| `BoxliteExecutor` | BoxLite microVM | 读写挂载到 `/workspace` | 抛出 `SandboxInitError` |

Direct 路径拥有宿主账号能够访问的文件、进程和网络权限。它会整理工作目录和环境变量，但它的执行强度仍然来自宿主账号权限。

BoxLite 路径建立 microVM，再把当前 Workspace 读写挂载进去。microVM 提供更强的进程边界，读写挂载也意味着命令仍可能修改 Workspace。隔离与只读是两个独立设置；小林说“只读检查”时，Agent 仍要选择只读动作，不能把 microVM 当成不会产生修改的保证。

当配置选择 `auto` 或 `boxlite` 而环境无法建立 BoxLite 时，构造过程显式失败。代码不会静默切换到 Direct。这样，失败会暴露在启动阶段，执行强度也不会在用户不知情时改变。

## 4. 收回结果：输出先作为数据进入下一轮

测试命令结束后，Executor 返回 `stdout`、`stderr` 和 `exit_code`。工具将它们整理成 `ToolResult`，Registry 结束 `tool.call` Span，Agent Loop 再发出完成阶段的 `ToolEvent`。

在写回下一次模型输入前，`wrap_untrusted()` 会给文件、Shell、网页、MCP 和 Subagent 结果加一对随机 nonce 围栏。测试日志里的文字会作为外部数据出现，即使日志中写着“忽略上面的要求”，它也没有因此获得 system 消息的身份。

现在回看完整主线。读图时从左向右追 `tool_call_id`，再从右向左检查失败状态是否回到了同一次调用。

**图 P07-A｜工具调用从请求到结果的合同**

![](images/P07/img1.jpg)

图里最重要的结论是：模型经 Provider 返回的响应提出工具请求；Registry 完成查找、转换、校验和计时；Tool 与 Executor 执行动作；`ToolResult.failed` 随结果回到下一次模型调用。每一段都有明确的所有者。

这时，小林的 Tool Registry 测试已经跑完。模型可以根据失败输出解释原因，也可以继续请求读文件。接下来三站都从这条已经闭合的主线扩展。

## 5. 接入远端工具：MCP 先被包装成 Tool

小林还要求“需要时查依赖文档”。如果文档能力由 MCP Server 提供，`connect_mcp_servers()` 先建立 transport、初始化 Session，再获取远端工具目录。每个远端工具会被 `MCPToolWrapper` 包装成 Pico Tool：

- 工具名加上 `mcp_<server>_` 前缀，降低不同 Server 的重名概率；
- 参数 Schema 沿用 MCP 的 `inputSchema`；
- 调用仍经过 Registry 的查找、校验、Trace 和总超时；
- MCP 返回的 `isError` 映射为 `ToolResult.failed=True`；
- 真正来自外层 Task 的取消继续向外传播。

因此，模型调用文档工具时仍然走“请求、校验、执行、结果”这条主线。MCP 增加了工具来源和 transport，没有新增一条绕开 Registry 的普通执行入口。

stdio MCP 还需要当前 Executor 支持派生进程。如果执行环境无法满足这个能力，连接阶段抛出 `SandboxInitError`。普通的单个 Server 连接异常会记录在对应 Server 上，已经成功连接的其他 Server 仍可保留。

远端返回的文档内容继续经过不可信数据围栏。MCP 身份说明了数据来自哪个工具，不能把外部文本提升为 system 指令。

## 6. 缩小可见目录：工具多时先搜索

当 Tool Registry 很大时，把所有 JSON Schema 放进每次 Provider 请求会占用上下文。`ToolSearchStrategy` 发现目录超过阈值后，只保留核心工具，并向模型提供两个元工具：

- `tool_search` 用 BM25 搜索隐藏目录，返回候选工具的名字、描述和参数 Schema；
- `tool_call` 按名字代理调用候选工具，最终仍回到 Registry 执行。

对小林这次请求，模型可以先搜索“依赖文档”，看到 MCP 文档工具，再通过 `tool_call` 发起实际调用。这个过程多了一步选择，检索结果也可能漏掉正确工具。因此，目录变小只说明模型看见的 Schema 变少，任务结果仍要由 Verifier 验收。

冻结的 Tool/MCP 实验给出了一个很直接的边界：在六个可比较成功任务上，模型可见 Schema 的估算 token 宏平均下降 `93.4513%`；control 通过 `23/24`，treatment 通过 `20/24`。该实验完成交付且测量有效，任务通过数回退使 `positive_claim_eligible=false`。这组结果支持“可见 Schema 显著减少”，不支持把该策略写成已经通过任务效果 Gate 的优化。

## 7. 运行子任务：独立调查也要回到原会话

storage 测试与 Tool Registry 测试互不依赖，主 Agent 可以调用 `spawn`。`SubagentManager.spawn()` 先检查当前会话的一小时滚动配额；通过后，它立即创建一个后台 Task，并把 task id 交回主 Agent。后台 Task 进入 `_run_subagent()` 后才等待全局 Semaphore 槽位，取得槽位后再建立独立 Executor 和受限工具集。

子任务能使用文件、Shell 和 Web 工具；工具集中没有消息发送工具，也没有继续 spawn 的工具。它最多运行 15 次模型迭代。这个限制让后台调查保持一层，并让 Provider、CPU 和 microVM 占用可以计数。

子任务有三种结构化完成结果：

| `SubagentStatus` | 含义 | 是否向原会话回注结果 |
|-|-|-|
| `COMPLETED` | 得到最终文本 | 是 |
| `FAILED` | 执行或 Executor 生命周期失败 | 是 |
| `EXHAUSTED` | 15 次迭代后仍无最终文本 | 是，以失败文案回注 |

配额拒绝发生在任务创建前，`spawn` 直接返回 `ToolResult(failed=True)`，不会留下后台 Task。取消沿真实 Task 传播，Trace 记录 `subagent.status=cancelled`，也不会产生一条结果回注。

对正常完成、失败或耗尽，Manager 会先等 Executor 完整退出，再把结果包装成不可信数据，构造 `Origin.SUBAGENT` 的 `TurnRequest`，提交回原 conversation。Scheduler 会把 system 来源强制按 APPEND 处理，因此后台结果排在原会话 Lane 中，不会中断正在运行的用户 Turn。

下面这张图同时画了四类执行位置。读图时先看每条线在哪里执行，再看结果回主模型前是否经过信任边界。

**图 P07-B｜工具与子任务的执行隔离边界**

![](images/P07/img2.jpg)

图里的强度有明显差异：Direct 使用宿主权限，BoxLite 使用 microVM，MCP 连接外部进程或服务，Subagent 拥有独立 Executor 和受限工具集。共同点是结果都按外部数据处理，并且最终回到原会话的生命周期里。

## 把整条请求串起来

现在可以按发生顺序复述小林的请求：

1. 主 Agent 请求 `exec` 运行 Tool Registry 测试；
2. Registry 转换并校验参数，Executor 运行命令；
3. 测试输出带 `failed` 状态和不可信围栏回到模型；
4. 模型通过 MCP 文档工具读取依赖资料，调用仍走 Registry；
5. 模型为 storage 问题创建一个受配额和并发限制的 Subagent；
6. 子任务退出 Executor 后，把结构化结果回注原 conversation；
7. 原会话 Lane 处理回注，主 Agent 汇总 API 日志、文档证据和 storage 调查结果。

这条链路能追踪进程内的会话归属、工具失败和子任务终态。外部工具已经产生的副作用不会因 Turn 取消自动撤销；后台任务也没有进程崩溃后的 durable execution 保证。需要事务或幂等的工具，要在工具自身和外部系统的合同里实现。

## 失败和取消从哪里收口

主线清楚后，再看分支会容易很多。

| 情况 | 收口位置 | 模型能看到什么 | 运行时还做什么 |
|-|-|-|-|
| 工具名或参数错误 | `ToolRegistry.execute()` | `ToolResult(failed=True)` 和纠错信息 | 不进入业务执行 |
| 普通工具超时 | Registry 与具体 Executor | 超时失败结果 | Executor 负责回收它启动的命令 |
| MCP `isError` 或远端异常 | `MCPToolWrapper.execute()` | 失败结果 | 保留 Server 与工具身份 |
| 外层取消 MCP 调用 | MCP wrapper | 无普通失败文案 | 继续抛出取消 |
| BoxLite 无法建立 | `build_executor()` | 启动错误 | 保持配置要求的执行强度 |
| Subagent 配额用尽 | `SubagentManager.spawn()` | `ToolResult(failed=True)` | 不创建后台任务 |
| Subagent 执行失败 | Subagent outcome | 围栏包裹的失败结果 | `subagent.status=failed` |
| Subagent 迭代耗尽 | Subagent outcome | 明确的预算耗尽结果 | `subagent.status=exhausted` |
| 会话停止 | Scheduler 与 SubagentManager | 不回注已取消子任务 | 等待取消收束 |

Registry 的 timeout 取消 Python await 后，外部进程是否已经停止还取决于具体 Executor。读工具实现时要同时检查“await 结束”和“资源回收”两件事。

网络工具还有一条独立边界。`WebFetchTool.execute()` 在把请求交给 Jina Reader 前，先检查原始 URL 的 scheme、hostname 和 DNS 解析结果，阻止私网、loopback 与 link-local 目标。Reader 以 JSON 返回结果时，当前 Reader 实现会在 `data.url` 中报告它观察到的最终 URL；Pico 对这个 URL 再做一次相同的 fail-closed 校验，通过后才读取并返回 `data.content`。`data.url` 缺失、格式错误、无法解析或落到私网时，工具返回 `ToolResult(failed=True)`，内容不会进入下一次模型输入。

这道 Gate 保护的是 Pico 的结果回传边界。Jina 在给出 JSON 之前已经完成上游抓取，所以它不能阻止托管 Reader 访问目标；上游协议变化和两次 DNS 解析之间的 TOCTOU 也仍需单独看待。调试这条路径时，要把“原始 URL 已校验”“Jina 报告 URL 已校验”和“上游是否已经抓取”分成三件事。

## 术语表

| 术语 | 在本章中的准确含义 |
|-|-|
| Tool Contract | 名字、描述、参数 Schema、执行方法和结果状态组成的调用合同 |
| Tool Registry | 统一完成注册、查找、参数处理、计时与调用 Trace 的分发器 |
| ToolResult | 带 `failed` 布尔值的字符串结果 |
| MCP wrapper | 把远端 MCP 工具翻译成 Pico Tool 的适配层 |
| SandboxExecutor | 命令执行环境的能力接口 |
| DirectExecutor | 使用宿主进程权限执行命令的后端 |
| BoxliteExecutor | 在 BoxLite microVM 中执行命令的后端 |
| Trust boundary | 外部文本进入模型上下文前的不可信数据边界 |
| Tool Search | 先检索隐藏工具目录，再代理调用的渐进式披露机制 |
| Subagent outcome | `COMPLETED`、`FAILED` 或 `EXHAUSTED` 的结构化子任务结果 |

## 源码锚点

第一遍按七站读文件，第二遍再落到这些符号：

| 顺序 | 文件与符号 | 只看什么 |
|-|-|-|
| 1 | `pico/agent/loop/main.py::AgentLoop._run_agent_loop` | Tool Event、Registry 调用和结果回填 |
| 2 | `pico/agent/tools/base.py::Tool.cast_params` | 字符串怎样按 Schema 安全转换 |
| 3 | `pico/agent/tools/base.py::Tool.validate_params` | 哪些参数约束在执行前检查 |
| 4 | `pico/agent/tools/registry.py::ToolRegistry.execute` | 查找、timeout、异常和 `failed` 收束 |
| 5 | `pico/sandbox/__init__.py::build_executor` | Direct 与 BoxLite 的选择和启动失败 |
| 6 | `pico/security/trust.py::wrap_untrusted` | 随机 nonce 围栏怎样构造 |
| 7 | `pico/agent/tools/web.py::WebFetchTool.execute` | 原始 URL 与 Jina 报告 URL 的两次回传 Gate |
| 8 | `pico/agent/tools/mcp.py::MCPToolWrapper.execute` | MCP 错误、timeout 与取消边界 |
| 9 | `pico/agent/tools/tool_search.py::ToolSearchController` | 隐藏目录怎样搜索和代理调用 |
| 10 | `pico/agent/subagent/manager.py::SubagentManager` | 配额、并发、Executor、回注和取消 |

调试一次调用时，先用 `tool_call_id` 找 `ToolEvent` 和 `tool.call` Span，再依次检查：工具是否注册、参数怎样转换、哪个 timeout 生效、用了哪个 Executor、`ToolResult.failed` 是什么、下一次模型输入有没有收到同一调用 ID 的结果。

## 用测试验证理解

| 想验证什么 | 先读哪个测试 |
|-|-|
| Registry timeout 与显式失败 | `tests/test_tool_registry_timeout.py` |
| MCP 包装、错误和取消 | `tests/test_mcp_tools.py` |
| Tool Search 的可见目录与代理调用 | `tests/test_agent_loop_tool_search.py` |
| Executor 合同和后端选择 | `tests/test_sandbox_unit.py` |
| 随机 nonce 不可信围栏 | `tests/test_security_trust.py` |
| URL、DNS、Jina 报告 URL 与私网目标检查 | `tests/test_security_network.py`、`tests/test_security_web_ssrf.py` |
| Subagent 配额、终态、回注和取消 | `tests/test_subagent_manager.py` |
| Tool/MCP 实验 Gate | `tests/test_picobench_tool_mcp_track.py` |

这些测试覆盖代码合同和冻结实验 reducer。`tests/test_sandbox_integration.py` 与 `tests/test_sandbox_cli_real_vm.py` 还需要相应的本地 Sandbox 或真实 microVM 环境。本章没有用单元测试结果推导完整安全证明。

## 25 分钟代码练习

目标：追完开头那条 Tool Registry 测试请求，再把 storage 调查接成一个子任务。

1. 在 `AgentLoop._run_agent_loop()` 找到 Provider 工具请求怎样进入 Registry；
2. 在 `ToolRegistry.execute()` 写下查找、转换、校验、计时和结果五个动作；
3. 在 `build_executor()` 确认当前配置会选择哪个后端；
4. 找到工具结果经过 `wrap_untrusted()` 并回到下一次模型输入的位置；
5. 在 `MCPToolWrapper.execute()` 找到 `isError` 和取消的不同路径；
6. 在 `ToolSearchController` 找到隐藏目录和代理调用；
7. 在 `SubagentManager` 找到配额检查、后台 Task 创建、Semaphore 等待、Executor 退出和回注。

建议边读边填：

```text
站点 | 输入 | 拥有者 | 失败状态 | 下一站
```

完成后回答：

- `"120"` 在哪里变成整数，转换失败时命令有没有开始？
- BoxLite 初始化失败后，为什么主线直接失败？
- Subagent 的 `FAILED` 与 spawn 配额拒绝分别落在哪种结构里？
- MCP 文档返回后，哪一层决定它在模型上下文中的信任级别？

## 本章复盘

- [ ] 能按七站复述一条工具请求；

- [ ] 能用 `tool_call_id` 对上请求、事件和结果；

- [ ] 能解释参数校验与工具业务代码的先后顺序；

- [ ] 知道 Direct 使用宿主权限，BoxLite 使用 microVM；

- [ ] 知道 BoxLite 的 Workspace 是读写挂载；

- [ ] 能追踪 MCP 工具怎样进入 Registry；

- [ ] 能区分 Schema 估算 token 与任务通过数；

- [ ] 能区分 spawn 配额拒绝与三种 Subagent outcome；

- [ ] 知道取消后的外部副作用需要工具自身处理；

- [ ] 能解释子任务结果怎样回到原 conversation 的 Lane。

## 接下来怎么读

- [P08｜Channels、Gateway、Cron 与 Delivery](https://icnoljnkix43.feishu.cn/wiki/LM0vwlNRqi08c0k9ilgcKsQSnte)：结果怎样送回具体聊天入口；
- [P10｜Tracing 与终态](https://icnoljnkix43.feishu.cn/wiki/OS4WwBltmi3v5gkfmQ8cPVmOnec)：`tool.call`、`subagent.run` 和 Turn 终态怎样进入证据链；
- [P11｜PicoBench](https://icnoljnkix43.feishu.cn/wiki/XTOEwv9vhig1IikThC8cOJXEnrg)：为什么中间指标改善仍要经过 task-success Gate；
- [工具与交付面试话术](https://icnoljnkix43.feishu.cn/wiki/WgEgwPeORibGvhkLUEEcOzp8nWc)：准备项目表达时，再进入逐字话术线。
