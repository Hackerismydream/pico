# Pico runtime 架构改进计划

> 目标：把 Pico 从“功能都挂在 `Pico` 对象上的 local agent harness”收敛成一个边界清晰、可测试、可解释、可继续演进的 runtime。
> 这份计划基于 GPT Pro 架构 review、当前 checkout 代码状态，以及多轮 subagent review。它不是 PR 计划，而是分阶段实施路线。

## 0. 当前判断

Pico 已经具备本地 coding agent runtime/harness 的雏形：`Pico.ask()` 控制循环、工具协议、workspace guard、session/run 持久化、trace/report、context packing、compaction、skills、subagents、TUI 和 evaluator 都已经落到代码里。

但当前架构的最大问题仍然是：`Pico` 承担了太多角色。它既是 runtime engine，又是 state store、policy facade、prompt facade、tool executor facade、session manager、subagent factory、plan-mode controller、memory controller 和 event publisher。

当前硬事实：

- `pico/core/agent.py` 仍然约 2813 行。
- `Pico.ask()` 仍然约 367 行。
- 上一轮改动只加了 `_complete_model_turn()`、`ToolPreflightResult`、`RuntimeSnapshot`、`RunState = TaskState` alias 等 seam。
- 这些 seam 有价值，但没有完成 GPT Pro 要求的主体瘦身。

因此后续工作的第一目标不是继续加小 helper，而是让 `Pico.ask()` 真正变薄，让 `Pico` 降级为 facade。

## 1. 目标架构

目标形态：

```text
CLI / TUI
  |
  v
Pico facade
  |
  v
RuntimeEngine.run()
  |-- RuntimeHost protocol
  |-- Prompt / Context facade
  |-- CompletionTurnResult
  |-- ModelDecisionAdapter
  |-- ToolValidator + PolicyEngine.before_tool()
  |-- ToolRunner.execute() -> ToolExecution + Effects
  |-- RuntimeControlPlane progress / final gate
  |-- RunState reducer -> RunStore / report / snapshot
```

边界原则：

- `Pico` 只负责装配、兼容 API、对外 facade。
- `RuntimeEngine` 只负责“什么时候调用哪个阶段”，不拥有 session、memory、workspace、tools、subagent 的所有权。
- `RunState` 是一次 run 的唯一 mutable snapshot。
- trace 是事件事实，不反向成为状态真相。
- report、TUI snapshot 从 `RunState` 派生。
- ToolRunner 只执行已经被 policy 允许的工具，返回结果和 effects。
- PolicyEngine 管“这个工具此刻能不能执行”；RuntimeControlPlane 管“任务是否该继续推进、final 是否可接受”。
- RuntimeEngine 只依赖 `RuntimeHost` protocol，不直接依赖完整 `Pico` 对象。
- reducer 消费内部 `RunEvent`，trace 是由 `RunEvent + RunState` 派生的审计输出，不作为 reducer 输入。

## 2. 阶段 0：锁行为基线

### 目的

在搬迁主循环前，先锁住当前行为。否则重构后无法判断是架构改进还是行为回退。

### 要做

补齐或确认以下 characterization tests：

- trace 不做全量线性顺序锁死，只锁必须出现的事件集合、关键 partial order 和 schema invariant。
  - `run_started < prompt_built < model_requested`
  - `model_requested < model_parsed`
  - tool 执行后 `task_state/report` 必须反映 `tool_steps`
  - `run_finished` 必须与 final state/report 一致
- checkpoint trigger：`freshness_mismatch`、`workspace_mismatch`、`context_reduction`、`tool_executed`、`run_finished`。
- completion gate：final 被 block 后自动触发 `list_files` 或 verification command。
- provider recovery：recoverable model error、truncation recovery。
- plan mode：只能读工具和写 active plan file。
- subagent notification：child run 完成后进入 parent history/session/report。
- skill slash 和 skill fork 行为。
- 明显事实不准确的 claim 可以提前修正，例如 `write_files atomic`、benchmark 泛化能力、multi-agent runtime 过度表述。

### 不做

- 不改 runtime 架构。
- 不新增 RuntimeEngine。
- 不调整 provider、TUI、subagent 行为。

### 验收

```bash
uv run ruff check .
uv run python -m pytest -q
```

重点测试：

```bash
uv run python -m pytest -q \
  tests/test_completion_controller.py \
  tests/test_runtime_control.py \
  tests/test_v4_runtime_harness.py \
  tests/test_runtime_consumers.py \
  tests/test_pico.py
```

## 3. 阶段 1：拆出 RuntimeEngine 主循环

### 目的

执行 GPT Pro 的第一优先级：把 `Pico.ask()` 主循环迁出，让 `Pico` 真正变成 facade。

### 要做

新增：

- `pico/core/runtime_engine.py`
- `RuntimeEngine.run(...)`
- `RuntimeHost` protocol
- `RunRequest`
- `RunResult`
- `CompletionTurnResult`

从 `Pico.ask()` 迁出：

- `while run_context.can_continue()` 主循环。
- prompt build 后的 provider call。
- recoverable model error recovery。
- truncation recovery。
- model output parse dispatch。
- tool 分支：`before_tool -> execute tool -> continue`。
- final 分支：`before_final -> block/force tool/finalize`。
- step limit / retry limit / stopped final decision。
- 将旧 provider 的 `str + last_completion_metadata` 在 host 层包成 `CompletionTurnResult`，让 RuntimeEngine 从第一天起不依赖 mutable metadata side channel。

`Pico.ask()` 保留：

- skill command 早返回。
- 创建 task/run 初始状态。
- 启动 run store。
- 调用 `RuntimeEngine.run(...)`。
- 返回 final answer。

### 不做

- 不重写 provider。
- 不重写 ToolRunner。
- 不改 RuntimeControlPlane 规则。
- 不改 ContextManager 内部。
- 不改 subagent 和 skill runtime。
- 不把 session/memory/workspace/tools 的所有权搬进 RuntimeEngine。

### 设计约束

`RuntimeEngine` 可以接收一个 runtime host，但不能接收裸 `Pico` 并任意调用内部方法。

可接受：

```text
engine.run(host: RuntimeHost, state: RunState, context: RunContext, request: RunRequest)
```

不可接受：

```text
RuntimeEngine(session, memory, workspace, tools, skill_catalog, subagent_manager, run_store, ...)
```

`RuntimeHost` 第一阶段只暴露编排所需的窄接口：

```text
build_prompt_for_turn(...) -> PromptBuildResult
complete_model_turn(...) -> CompletionTurnResult
emit_runtime_event(...) -> None
execute_tool_request(...) -> ToolStepResult
handle_blocked_final(...) -> ToolRequest | None
finish_run(...) -> RunResult
```

阶段 1 可以由 `Pico` 实现这个 protocol，也可以用 `PicoRuntimeHost(Pico)` adapter 包一层。但 `RuntimeEngine` 不应该 import `Pico`，也不应该调用 `Pico` 私有方法。

### 验收

- `Pico.ask()` 不再包含 `while` 主循环。
- `Pico.ask()` 控制在 80 行以内。
- `agent.py` 从约 2813 行降到 2400 行以下。
- `RuntimeEngine` 控制在 400-500 行以内。
- `RuntimeEngine` 单个方法不超过 120 行。
- `RuntimeEngine` 只依赖 `RuntimeHost` protocol。
- `RuntimeEngine` 不直接写 `self.session`。
- `RuntimeEngine` 不直接写 `RunStore` / `SessionStore`，除非通过 lifecycle 或 host。
- `RuntimeEngine` 不直接调用 `approval_callback`。
- `RuntimeEngine` 不直接调用 `subagent_manager`。
- `RuntimeEngine` 不直接知道 `skill_catalog`。
- `RuntimeEngine` 不直接读写 `current_task_state` 之外的 `Pico` mutable fields。
- 全量测试通过。

## 4. 阶段 2：迁出 lifecycle helper

### 目的

阶段 1 只迁主循环还不够。`_execute_tool_step()`、`_finish_run()` 等 lifecycle helper 如果继续留在 `Pico`，`Pico` 仍然是 runtime engine。

### 要做

迁出：

- `_execute_tool_step()`
- `_finish_run()`
- checkpoint/report/finalization 的重复写入逻辑

新增或扩展：

- `pico/core/run_lifecycle.py`
- `RunLifecycle.execute_tool_step(...)`
- `RunLifecycle.finish_run(...)`

### 不做

- 不改变 report schema。
- 不改变 trace event 名称。
- 不改变 session history 写入顺序。

### 验收

- `agent.py` 降到 2000-2200 行。
- `_execute_tool_step()`、`_finish_run()` 不再作为 `Pico` 的核心实现存在，最多保留兼容 wrapper。
- tool execution、checkpoint、report、completion gate 测试全部通过。

## 5. 阶段 3：收敛 TaskState 为唯一 RunState

### 目的

解决 GPT Pro 的第二个 P0：状态来源不唯一。

当前 `TaskState` 已经是事实上的 run state，不应该新增一套并行 `RunState`。正确路径是把 `TaskState` 正名和收敛成唯一 `RunState`，同时保留 `TaskState` alias 兼容旧代码。

### 要做

重命名或收敛：

- `RunState` 成为 canonical class。
- `TaskState = RunState` 作为兼容 alias。
- `task_state.json` 文件名暂时保持不变，避免 artifact 迁移成本。

优先统一写入口的字段：

- `attempts`
- `tool_steps`
- `last_tool`
- `status`
- `stop_reason`
- `final_answer`
- `stage`
- `checkpoint_id`
- `resume_status`

第二批统一：

- `tasks`
- `changed_paths`
- `verifications`
- `completion_gate`
- `artifact_graph`
- `verification_plan`
- `control_decisions`
- `runtime_reminders`
- `consumer_errors`

第三批只做 run snapshot：

- `subagents`
- prompt/completion metadata
- durable memory promotion/rejection/supersede summary

### 不做

- 不把 session memory 搬进 RunState。
- 不把 checkpoint body 搬进 RunState。
- 不把完整 prompt metadata 塞进 RunState。

### 验收

- 不存在两个状态类同时被写。
- `RunContext` 不再持有 `_attempts/_tool_steps` fallback。
- `report["task_state"]`、report top-level、`task_state.json` 的关键字段一致。
- 旧 `.pico/runs/<run_id>/task_state.json` 能被 load。

## 6. 阶段 4：引入 reducer

### 目的

把“事件更新状态”显式化，避免 `emit_trace()`、`_update_derived_runtime_state()`、session fallback 到处改状态。

### 要做

新增：

- `pico/core/run_reducer.py`
- `pico/core/run_events.py`
- `reduce_run_state(state, event: RunEvent) -> RunState`

关键区分：

- `RunEvent` 是内部 domain event，面向状态迁移。
- `TraceEvent` 是审计 event，面向外部复盘和报告。
- `SessionEvent` 是会话 event，面向跨 turn 的 session 记录。
- reducer 只消费 `RunEvent`，不直接消费 `trace.jsonl` envelope。

推荐流程：

```text
RuntimeEngine emits RunEvent
  -> reducer updates RunState
  -> trace adapter converts RunEvent + RunState into TraceEvent
  -> session adapter converts selected RunEvent into SessionEvent
```

第一批 reducer 事件：

- `run_started`
- `model_attempted`
- `tool_executed`
- `stage_changed`
- `task_list_updated`
- `verification_recorded`
- `completion_assessed`
- `runtime_reminder_emitted`
- `control_decision_recorded`
- `checkpoint_created`
- `run_finished`
- `run_stopped`
- `model_error`
- `output_truncated`

### 暂不覆盖

- `prompt_built` 的完整 metadata。
- `history_compacted` 的正文。
- durable memory promotion/rejection 细节。
- subagent 全生命周期。
- checkpoint body。

### 验收

- 给定固定 `RunEvent` 序列，reducer 输出确定的 `RunState`。
- `_update_derived_runtime_state()` 被删除，或降级为纯派生 helper。
- `emit_trace()` 不再隐式修改多个状态源。
- `TraceEvent` 由 `RunEvent` 派生，但 reducer 不消费 trace schema。

## 7. 阶段 5：PolicyEngine 和 PlanModeController

### 目的

解决 policy/control 分散问题，但不要做成复杂 rule DSL。

### 分层

`ToolSpec / ToolPolicy`：

- 声明静态能力、schema、默认 effects。
- 不做运行期判断。

`ToolValidator`：

- tool exists / registry resolve
- args shape / required fields
- tool-specific static validation

`PolicyEngine.before_tool()`：

- allowed tools
- 编排 `ToolValidator` 的静态校验结果，但不拥有每个 tool 的 arg validation
- runtime mode
- write scope
- prior-read/freshness
- read-only mode
- approval needed
- repeated call

`RuntimeControlPlane`：

- progress guard
- completion gate
- final blocking

`RuntimeEngine`：

- 编排调用 policy、tool、control plane。
- 不内化规则。

### PlanModeController

新增：

- `pico/features/plan_mode.py`
- `PlanModeController`

输入/输出：

- `enter(topic) -> PlanModeState`
- `exit() -> PlanExitResult`
- `prompt_section(state) -> str`
- `allowed_effects(state) -> set[Effect]`
- `is_active_plan_write(tool_request, state) -> bool`
- `final_gate_requirements(state) -> list[Requirement]`

收拢现有 facade：

- `enter_plan_mode()`
- `exit_plan_mode()`
- `active_plan_path()`
- `active_plan_has_content()`
- `plan_mode_text()`
- `allowed_effects_for_plan()`

`PlanModeController` 不直接写 session。它返回 state/effects/requirements，由 host/lifecycle 落盘。

注意：

- `TaskState.stage = "planning"` 是任务阶段。
- `runtime_mode = "plan"` 是执行权限模式。
- 两者不能混为一谈。

### 验收

- 任意 tool rejection 有结构化 `PolicyDecision`。
- 请求流程清晰：`ToolRequest -> ToolRegistry.resolve() -> ToolValidator.validate_static() -> PolicyEngine.evaluate_runtime_policy() -> ToolRunner.execute()`。
- 同一拒绝原因在 trace/report/TUI 中一致。
- plan mode 不再靠 prompt/session/tool validation/completion gate 各自解释。
- `RuntimeControlPlane` 仍只管 progress/final gate。

## 8. 阶段 6：最小 Effect taxonomy + ToolRunner effects 化

### 目的

先定义稳定的最小 effects 语义，再解决 GPT Pro 点名的 ToolRunner 边界泄漏。不能先造临时 effects 结构，再在下一阶段推翻。

### 要做

先定义最小 `Effect` taxonomy：

- `workspace_read`
- `workspace_write`
- `runtime_state_read`
- `runtime_state_write`
- `process_read`
- `process_exec`
- `artifact_write`
- `user_interaction`

`ToolRunner.execute()` 返回：

- `content`
- `metadata`
- `effects`

最小 effects：

- `workspace_changed`
- `affected_paths`
- `diff_summary`
- `artifact`
- `verification`
- `read_ledger_update`
- `memory_hints`
- `effective_effects`

第一批删除 callback：

- `emit_trace`
- `update_memory_after_tool`
- `update_tool_policy_after_tool`
- `record_process_note_for_tool`

改为：

- `RuntimeEngine.apply_tool_effects(execution)`

第二批迁出 callback：

- `validate_tool`
- `tool_example`
- `tool_rejection_recovery_message`
- `changed_path_read_stall`
- `repeated_tool_call`
- `consecutive_read_only_tool_count`
- `approve`
- `is_active_plan_file_write`

这些进入 `PolicyEngine.before_tool()`。

### 验收

- 最小 `Effect` taxonomy 已存在，并被 ToolRunner output 使用。
- ToolRunner 可独立测试。
- ToolRunner 不写 trace。
- ToolRunner 不改 memory。
- ToolRunner 不改 read ledger。
- ToolRunner 不调用 approval callback。

## 9. 阶段 7：用 effects 替代 read_only 语义判断

### 目的

在阶段 6 的最小 effects 基础上，逐步修正 `read_only` 混乱：它现在既表示 workspace 不写，又被用于 runtime-state mutation，还不能表达 shell 动态读写。

### 扩展 effects

- `external_read`
- `external_write`

### 兼容策略

- `ToolPolicy.to_dict()` 继续输出 `read_only`。
- 新增 `effects` 字段。
- 老工具没有 effects 时，用 `read_only` 推导。
- trace/report 继续写 `read_only`，同时新增 `effects` 和 `effective_effects`。
- plan mode/read-only mode 逐步改成看 effects。
- `run_shell` 支持动态 effects：只读 shell 命令是 `process_read`，其他是 `process_exec`。

### 验收

- `todo_write/todo_update` 不再被语义上误认为 workspace read-only。
- read-only mode 下危险 shell 被拒，只读 shell 被允许。
- trace/report 能同时兼容旧 `read_only` 和新 effects。

## 10. 阶段 8：TUI command bus 和 snapshot

### 目的

让 TUI 不再直接窥探 runtime 内部。

### 可提前做

- `StatusBar` 只吃 `RuntimeSnapshot`。
- 阶段 2 或阶段 3 后，先做薄版本 command bus：`TUI -> Pico.handle_command()`。
- 再新增 `TuiCommandBus.dispatch(command, args) -> CommandResult`。
- command bus 早期仍可临时调用 `Pico` facade。
- 先把 `/tasks`、`/verify`、`/compact`、`/plan`、`/execute`、`/reset` 从 TUI 直接 agent 调用，搬到 facade command。

### 等 RunState 稳定后做

- TUI 变成纯 snapshot/event consumer。
- slash command 不直接调用 `agent.run_tool()`。
- slash command 不直接调用 `agent.subagent_manager.spawn()`。
- approval 保持 callback 或 command bus。

### CommandResult

建议字段：

- `messages`
- `run_request`
- `snapshot`
- `errors`

### 验收

- `tests/test_tui.py` 覆盖 command bus。
- TUI 不直接调用 `agent.run_tool()`。
- TUI 不直接调用 `agent.subagent_manager.spawn()`。
- StatusBar 不 fallback 到 session/current_task_state。

## 11. 阶段 9：统一 subagent / delegate / skill fork

### 目的

解决四套入口混乱：`delegate`、`agent Explore`、`Worker`、skill fork。

### 要做

新增：

- `SubagentInvocation`
- `ChildRunProfile`

字段：

- `source = delegate | agent | skill_fork | tui`
- `profile = Explore | Worker`
- `prompt`
- `background`
- `write_scope`
- `max_steps`

统一规则：

- `delegate` 变成 `source=delegate, profile=Explore, background=False` 的兼容包装。
- skill fork 变成 `source=skill_fork, profile=Explore, background=False`。
- TUI `/subagent` 只发 command bus，不直接 spawn。
- Worker 继续要求 write_scope。

### 验收

- `delegate`、`agent`、skill fork 产生同一种 notification schema。
- Explore 只读约束不退化。
- Worker write_scope 越界测试保持。
- `send_message` 续上下文行为保持。
- `task_stop` 取消语义保持。

## 12. 阶段 10：Provider CompletionResult 和 clients.py 拆分

### 目的

解决 provider 抽象泄漏：runtime 不应靠 mutable `last_completion_metadata` 作为主协议。

### 要做

阶段 1 先新增内部 normalized result：

- `CompletionTurnResult(text, metadata, truncated=False, recoverable_error=False)`

阶段 10 再新增 provider-level result：

- `CompletionResult(text, metadata)`
- 以后可扩展：`usage`、`finish_reason`、`cache`、`transport`、`raw_metadata`

兼容策略：

- `_complete_model_turn()` 接受旧 `str` 和新 `CompletionResult`。
- client 逐步返回 `CompletionResult`。
- `last_completion_metadata` 保留一轮兼容测试，但不再是主路径。
- RuntimeEngine 从阶段 1 开始只吃 `CompletionTurnResult`，不直接读 `last_completion_metadata` 或 `supports_prompt_cache`。

拆分：

- `pico/providers/base.py`
- `pico/providers/fake.py`
- `pico/providers/openai_http.py`
- `pico/providers/openai_sdk.py`
- `pico/providers/anthropic_http.py`
- `pico/providers/anthropic_sdk.py`
- `pico/providers/ollama.py`
- `pico/providers/extractors.py`

### 验收

- truncation recovery 不回退。
- recoverable empty text 不回退。
- usage/cache metadata 继续进入 prompt/report metadata。
- provider tests 全部通过。

## 13. 阶段 11：Evaluator / metrics 降级为 harness regression

### 目的

把 evaluator 定位修正为 deterministic harness regression，而不是泛化 benchmark claim。

### 要做

新增：

- `Runner.run(prompt, config) -> RunArtifactRefs`
- `PicoRunner`

调整：

- `BenchmarkEvaluator` 只依赖 Runner 和 artifacts。
- metrics 只读 report/trace/artifacts。
- 不从 live `Pico` 或 private fields 偷读状态。
- 命名逐步改成 `harness_regression`。

保留：

- budget 判定。
- verifier 判定。
- expected artifact 判定。
- non-failure stop reason 判定。

### 验收

- 现有 benchmark artifact 仍输出。
- metrics 从 artifacts 聚合。
- 对外文档不再说 benchmark 证明 agent 泛化能力。

## 14. 阶段 12：文档和 claim 修正

### 目的

让 README、面试材料、项目叙事和代码事实一致。

### 要改

- 明显事实不准确的 claim 可以提前改，不必等阶段 12。
- “multi-agent runtime” 改成 “bounded child-run subagent prototype”。
- “benchmark system” 改成 “deterministic harness regression”。
- “policy engine” 在落地前改成 “tool guardrails + runtime gates”。
- “context optimization” 改成 “sectioned context packing with character-budget reduction and approximate token accounting”。
- 删除或实现 `write_files atomic` 说法。
- `read_only` 文档改成 effects taxonomy 兼容字段。

### 验收

- README 不夸大。
- docs 不再把 fragile prototype 写成 production-grade runtime。
- 面试叙事能同时讲清优点和技术债。

## 15. 总体验收标准

最终目标：

- `Pico.ask()` 小于 80 行。
- `agent.py` 第一轮小于 2400 行。
- `agent.py` 第二轮小于 2200 行。
- 后续目标小于 1800 行。
- `RuntimeEngine` 不成为新 god object。
- `RunState` 是唯一 run snapshot。
- `ToolRunner` 不依赖 callback bag。
- TUI 状态读取经 snapshot/command bus。
- provider 主协议不依赖 mutable `last_completion_metadata`。
- evaluator/metrics 只读 artifacts。

全局 gate：

```bash
uv run ruff check .
uv run python -m pytest -q
```

## 16. 推荐实施顺序

建议按 5 个 milestone 执行，避免 12 个阶段过长导致实施失焦。

### Milestone 1：锁行为 + 拆主循环

包含：

- 阶段 0：锁行为基线
- 阶段 1：拆 RuntimeEngine 主循环
- 阶段 2：迁出 lifecycle helper

核心验收：

- `Pico.ask() < 80 行`
- `ask()` 不含 while 主循环
- `RuntimeEngine` 只依赖 `RuntimeHost` protocol
- `_execute_tool_step()` / `_finish_run()` 迁出或只保留 wrapper
- 全量测试通过

这是最重要的一批，直接解决 GPT Pro 最大 P0：`Pico` god object 和 `ask()` 过重。

### Milestone 2：RunState + lifecycle state ownership

包含：

- 阶段 3：TaskState -> RunState 收敛
- 阶段 4：RunState reducer

核心验收：

- `RunState` 是唯一 run snapshot
- `RunContext` 不再复制 attempts/tool_steps
- session 不再作为 run state fallback
- report/task_state/snapshot 关键字段一致
- reducer 对固定 `RunEvent` 序列确定

### Milestone 3：Policy + effects + ToolRunner 边界

包含：

- 阶段 5：PolicyEngine + PlanModeController
- 阶段 6：最小 Effect taxonomy + ToolRunner effects 化
- 阶段 7：用 effects 替代 read_only 语义判断

核心验收：

- tool rejection 全部有 `PolicyDecision`
- plan/prior-read/write_scope/read-only/approval/repeated-call 走同一个 before_tool
- ToolRunner 不调用 approval/memory/trace/read ledger
- ToolRunner 可独立测试

### Milestone 4：外围解耦

包含：

- 阶段 8：TUI command bus 和 snapshot
- 阶段 9：统一 subagent / delegate / skill fork

核心验收：

- TUI 不直接读 `current_task_state/session/subagent_manager`
- delegate/agent/skill_fork 统一 notification schema
- Worker write_scope 测试保留
- Explore 只读约束不退化

### Milestone 5：provider/evaluator/docs 收口

包含：

- 阶段 10：Provider CompletionResult 和 clients.py 拆分
- 阶段 11：Evaluator / metrics 降级为 harness regression
- 阶段 12：文档和 claim 修正

核心验收：

- RuntimeEngine 不依赖 `last_completion_metadata`
- metrics 只读 artifacts
- docs 不 overclaim
- provider smoke 不回退

## 17. 关键风险

### 风险 1：RuntimeEngine 变成新的 god object

缓解：

- RuntimeEngine 只编排，不拥有 session/memory/workspace/tools。
- RuntimeEngine 只依赖 `RuntimeHost` protocol，不直接 import `Pico`。
- RuntimeHost 暴露窄方法，不暴露完整 agent 对象。
- 单方法不超过 120 行。
- 构造函数不接一堆可变大对象。

### 风险 2：state reducer 一次性过大

缓解：

- 先收核心字段，再收 completion/report 字段。
- prompt metadata、durable memory、subagent lifecycle 暂不进 reducer 核心。
- reducer 消费 `RunEvent`，不要消费 trace schema。

### 风险 3：policy 变成过度设计 DSL

缓解：

- 只做 deterministic preflight。
- 不接管 model retry。
- 不接管 completion gate。
- Tool-specific static validation 留给 `ToolValidator`，PolicyEngine 只做 runtime policy。

### 风险 4：TUI 重构抢跑

缓解：

- 先 command bus，后纯 consumer。
- 没有统一 RunState 前，不做完整 UI state reducer。

### 风险 5：provider 改动影响真实模型调用

缓解：

- 阶段 1 先引入内部 `CompletionTurnResult`，provider clients 暂不大拆。
- `CompletionResult` 先兼容旧 `str`。
- `last_completion_metadata` 保留一轮兼容。
- 先 fake/provider tests，再真实 provider smoke。

## 18. 当前下一步

下一步应该只做一件事：

> 开始阶段 0-1：补齐 runtime loop characterization tests，然后新增 `RuntimeEngine.run()`，把 `Pico.ask()` 的 while 主循环迁出。

阶段 1 完成前，不应该继续：

- 扩大 TUI 重构。
- 扩大 provider 拆分。
- 继续给 `Pico` 加 helper。
- 继续做只铺 seam 但不降 `agent.py` 行数的改动。

阶段 1 的第一版设计必须先写清楚：

- `RuntimeHost` protocol 方法列表。
- `RunRequest` / `RunResult` / `CompletionTurnResult` 数据结构。
- RuntimeEngine 禁止直接访问的 Pico mutable fields。
- trace characterization 的 partial order，而不是全量顺序快照。
