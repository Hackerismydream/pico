# 从 Bitz 学 Pico 的 TUI 设计

这份笔记只看 Bitz 对 Pico 有迁移价值的 TUI 设计。Bitz 的路径是 `/Users/martinlos/code/Bitz`，主要参考了 `tui.py`、`tui/app.py`、`tui/widgets/*`、`agent/loop.py`、`agent/context.py` 和 `tests/test_tui_*.py`。

## Pico 当前落地状态

Pico 已经把 Bitz 里最有价值的 TUI 结构迁移到了自己的 runtime 上：

- 入口：`pico` 默认进入 TUI，`pico --tui` 和 `pico-tui` 作为显式 TUI 入口，`pico --repl` 保留旧 REPL。
- UI：`PicoTuiApp`、`ChatLog`、`InputBar`、`ToolCard`、`ConfirmPrompt`、`StatusBar`。
- 运行方式：TUI 前台保持 Textual event loop，后台用 executor 调 `Pico.ask()`。
- 可观测性：runtime 发 `prompt_built`、`tool_started`、`tool_finished`、`run_finished` 等事件，TUI 订阅后实时显示工具卡片和上下文状态。
- 审批：CLI 继续使用同步 `input()`；TUI 使用 `approval_callback` 挂内联 `ConfirmPrompt`，不会阻塞 UI 线程。

这个版本不是装饰性的聊天壳，而是 v4 runtime harness 的可视化入口。面试里可以把它讲成三层：底层 runtime 负责真实执行和记录，中间 event/callback 把运行过程变成结构化事件，上层 TUI 只负责展示和审批交互。

## Bitz 的 TUI 架构

Bitz 用的是 `textual>=3.0,<4.0`。入口在 `tui.py`，启动链路很直接：

```text
tui.py
  -> load .env
  -> ModelStore.init_from_env()
  -> LLMAdapter
  -> SkillRegistry
  -> SessionStore
  -> Context
  -> Agent
  -> BitzApp.run()
```

`BitzApp` 是 Textual 的 `App`。它不重写 agent 的核心 loop，而是把已有同步 agent 包进 TUI：

```text
InputBar submit
  -> ChatLog add user message
  -> _run_agent()
  -> asyncio.create_task(_agent_loop())
  -> loop.run_in_executor(None, agent.run, ...)
  -> result 回到 UI thread
  -> ChatLog / StatusBar / ConfirmPrompt 更新
```

这点对 Pico 很重要。我们不应该为了 TUI 重写 `Pico.ask()`。Pico 现在的 runtime 已经有 trace、session events、tool policy、checkpoint。TUI 应该是一个显示层和交互层，接在 runtime 外面。

## 组件拆分

Bitz 的组件拆得比较清楚：

- `ChatLog`：主消息流，负责挂载 user、assistant、tool card。
- `InputBar`：多行输入、Enter 发送、上下键历史、Esc 取消、斜杠命令。
- `ToolCard`：工具调用状态卡，running 展开，success 折叠，error 展开，diff 默认展开。
- `ConfirmPrompt`：内联审批，不弹阻塞 input。
- `StatusBar`：模型名、step、token、任务数、当前目录。
- `CommandPopup`：斜杠命令补全。
- `SessionRestoreBanner` / `SessionListScreen`：恢复历史会话。
- `ModelSelectScreen` / `ModelAddScreen`：模型切换和新增。

Pico 没有一次性搬完 Bitz 的所有 UI，而是先落地和 runtime harness 强相关的 5 个组件：

```text
PicoApp
ChatLog
InputBar
ToolCard
StatusBar
ConfirmPrompt
```

模型管理和 skill 浏览暂时没有搬；session 列表和 resume 已经用 `/history`、`/resume` 暴露。Pico 当前重点是面试可讲的 runtime/harness，所以 TUI 要把 runtime 过程显示清楚，而不是做复杂桌面应用。

## Bitz 怎么处理同步 Agent 和异步 UI

Bitz 的 agent loop 是同步的，TUI 不能让它阻塞主线程。它用两层机制解决：

```python
asyncio.create_task(self._agent_loop(user_input))
await loop.run_in_executor(None, self._agent.run, user_input, cancel_event, confirmed_tools, skip_add_user)
```

UI 主线程继续处理键盘和渲染。后台线程跑 agent。后台线程想更新 UI 时，走：

```python
app.call_from_thread(...)
```

Pico 可以照这个模式做。当前 `Pico.ask()` 是同步函数，适合直接放进 executor。要注意的是，Pico 的工具执行和 trace 写入都在 runtime 内部完成，TUI 不应该直接绕过 `run_tool()`。

## Bitz 怎么显示工具执行

Bitz 在 `BitzApp._install_tool_logger()` 里 monkey-patch 了 `agent.tools.execute`：

```text
原 execute
  -> UI 先挂 ToolCard running
  -> 调原 execute
  -> 根据 ToolResult 更新 success/error/diff
```

这个做法对 Bitz 合理，因为它的工具层返回 `ToolResult`。但 Pico 不建议照搬 monkey-patch。Pico v4 已经有 `trace.jsonl` 和 `_last_tool_result_metadata`，更稳的方式是让 runtime 提供一个可选 callback：

```python
on_runtime_event(event: dict) -> None
```

然后在这些位置发事件：

- prompt_built
- model_requested
- model_parsed
- tool_started
- tool_finished
- checkpoint_created
- run_finished

TUI 订阅这些事件，把 tool_started 显示成 running card，把 tool_finished 显示成 success/error/diff/artifact。这样 TUI 和 runtime 的边界更干净，也不会因为 monkey-patch 漏掉内部状态。

## Bitz 怎么处理确认

Bitz 的工具返回 `ToolResult.confirm_required` 时，agent 暂停，把 pending confirm 存在 `_pending_confirms`。TUI 收到 `[CONFIRM_REQUIRED]` 后挂 `ConfirmPrompt`，用户按 `y/n` 或左右键选择，再调用 `agent.confirm_pending()`。

Pico 当前 approval 是同步 `input()`。TUI 里不能这样做，否则会卡住 Textual。Pico 要把 approval 抽象成 callback：

```python
approval_callback(name, args, metadata) -> bool
```

CLI 模式继续用 `input()`，TUI 模式返回一个 Future，等 `ConfirmPrompt` resolve。这个改动比改 UI 更关键。否则 Pico 能启动 TUI，但一遇到 risky tool 就会阻塞。

## Bitz 的命令系统

`InputBar` 把 `/xxx` 解析成 `CommandSubmitted`，`CommandPopup` 从基础命令和 skill triggers 生成补全列表。Bitz 内置命令包括：

- `/help`
- `/new`
- `/clear`
- `/compact`
- `/theme`
- `/models`
- `/skill`
- `/sessions`
- `/resume`
- `/title`

Pico 当前 TUI 已经支持：

- `/help`
- `/clear`
- `/new`
- `/session`
- `/memory`
- `/context`
- `/trace`
- `/history`
- `/resume`
- `/compact`
- `/plan`
- `/execute`
- `/approval auto|ask|never`

这里的 `/context`、`/trace`、`/compact` 和 `/plan` 比 `/models` 更重要，因为 Pico 的卖点是 runtime harness。`/context` 直接读 `last_prompt_metadata["context_usage"]`，`/trace` 显示当前 run 的 trace path 和最近事件，`/compact` 改写可恢复 session history，`/plan` 切换 runtime mode 并把写操作限制在 plan 文件里。

## Bitz 的测试方式

Bitz 的 TUI 测试大量使用 Textual 的 `run_test()`：

```python
async with app.run_test() as pilot:
    bar = app.query_one(InputBar)
    bar._input.text = "/help"
    await pilot.press("enter")
    await pilot.pause()
```

它测试的不是截图，而是组件状态和消息：

- 输入框是否发出 `MessageSubmitted`
- `/help` 是否产生 assistant message
- `ToolCard` success 后是否折叠
- error 后是否展开
- `/models` 是否 push screen
- `/theme` 是否更新 app.theme

Pico 做 TUI 时也应该先写这些测试。不要一开始就上 Playwright 或终端截图。Textual 自带测试 harness 已经够用。

## Pico 的实现方案

代码放在：

```text
pico/tui/app.py
pico/tui/widgets.py
pico/tui/main.py
```

CLI 入口：

```bash
pico
pico --tui
pico --repl
```

或者新增脚本：

```bash
pico-tui
```

启动后创建同一个 `Pico` 实例，只是把原来的 REPL loop 换成 Textual App。用户输入通过 executor 调 `agent.ask()`，结果回到 `ChatLog`。

Runtime 补了两个 hook：

```text
Pico.event_callback
Pico.approval_callback
```

这样 TUI 可以实时显示工具执行过程，而不是等 `ask()` 完成后一次性显示最终结果。对 Pico 来说，这一步是核心，因为它能把 v4 的 trace/session/tool policy 可视化出来。

后续可以继续做 Pico 自己的可观测面板：

- Context 面板：section token、budget、free tokens。
- Tool 面板：tool policy、allowed tools、artifact path、diff summary。
- Session 面板：session events、current turn、checkpoint。
- Trace 面板：按 phase 展示 recent events。

## 不建议照搬的部分

Bitz 的 monkey-patch 工具 logger 对 Pico 不合适。Pico 已经把工具执行集中在 `run_tool()`，应该在 runtime 里发事件，不应该从 UI 层替换工具函数。

Bitz 的模型管理也不急着搬。Pico v4 已经在 provider 层处理 OpenAI-compatible、Anthropic-compatible、Anthropic SDK 和 DeepSeek。TUI 第一版只显示当前模型，切换模型放到第二阶段。

Bitz 的视觉主题可以借鉴结构，但不要照搬品牌风格。Pico 的 TUI 应该更像一个 runtime console：安静、密度高、重证据，重点显示 prompt usage、tool policy、trace 和 artifacts。

## 已交付范围

1. 加了 `textual` 依赖和 `pico-tui` entrypoint。
2. 实现了 `PicoTuiApp`、`ChatLog`、`InputBar`、`StatusBar`、`ToolCard`、`ConfirmPrompt`。
3. `InputBar` 支持 Enter 发送、上下键历史、Esc cancel。
4. 后台 executor 调 `Pico.ask()`，UI 不阻塞。
5. runtime event callback 驱动工具卡片、上下文状态和 trace 状态。
6. TUI 内联审批接入 `approval_callback`，不再调用阻塞式 `input()`。
7. TUI 命令覆盖 history/resume、compact、plan/execute 和 approval。
8. 测试覆盖命令、后台 agent 执行、工具卡片、内联审批、runtime event/approval callback。

这样做完，Pico 的 TUI 不是装饰层，而是 v4 runtime harness 的可视化入口。
