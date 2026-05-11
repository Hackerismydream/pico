# Pico runtime 架构改造实施记录

本轮改造按 `05-runtime架构改进计划.md` 的前五个 milestone 推进，但没有做破坏性重写。核心目标是先把 `Pico` 从主循环和执行生命周期里解耦出来，降低 `agent.py` 的复杂度，同时保持现有 trace/report/session 行为兼容。

## 已完成

### 1. RuntimeEngine 主循环拆分

- 新增 `pico/core/runtime_engine.py`
- 新增 `RuntimeHost`、`RunRequest`、`RunResult`、`CompletionTurnResult`
- `Pico.ask()` 不再包含 `while run_context.can_continue()` 主循环
- `Pico.ask()` 当前约 79 行，只负责 turn 初始化、skill 快路径和调用 engine
- `RuntimeEngine` 通过 host 方法访问 prompt、model、tool、final、trace/state 写入，不再直接依赖 `Pico.runtime_control`、`Pico._runtime_reminder_keys`、`Pico.model_client` 等内部字段

### 2. RunLifecycle 拆分

- 新增 `pico/core/run_lifecycle.py`
- `_execute_tool_step()` 和 `_finish_run()` 主体迁出到 `RunLifecycle`
- `Pico` 只保留兼容 wrapper
- 工具执行后的 trace、checkpoint、report/finalization 仍保持原 schema

### 3. RunState / RunEvent / reducer

- `RunState` 成为 canonical class
- `TaskState = RunState` 作为兼容 alias
- `RunContext` 不再维护 `_attempts/_tool_steps` fallback
- 新增 `pico/core/run_events.py`
- 新增 `pico/core/run_reducer.py`
- model attempt 和 tool executed counter 已经走 `RunEvent -> reduce_run_state`

### 4. PolicyEngine 和 effects taxonomy

- 新增 `pico/core/policy_engine.py`
- `Pico.preflight_tool()` 改为委托 `PolicyEngine.before_tool()`
- approval、repeated identical call、read-only stall warning 已从 `ToolRunner` 挪到 policy preflight
- 新增 `Effect` taxonomy：
  - `workspace_read`
  - `workspace_write`
  - `runtime_state_read`
  - `runtime_state_write`
  - `process_read`
  - `process_exec`
  - `artifact_write`
  - `user_interaction`
- `ToolPolicy.to_dict()` 保留 `read_only` 兼容字段，同时输出 `effects`
- `ToolRunner` 返回 `ToolExecutionResult(content, metadata, effects)`
- `ToolRunner` 不再持有 trace/memory/read-ledger/process-note/approval callbacks
- `run_shell` 会按命令动态标记 `process_read` / `process_exec`

### 5. ToolPolicyController / PlanModeController

- 新增 `pico/core/tool_policy.py`
- prior-read、freshness、write_scope、plan-mode write 约束、read ledger 更新迁出 `agent.py`
- 新增 `pico/features/plan_mode.py`
- plan mode 的 session shape、active plan file、enter/exit/prompt section 迁出 `agent.py`

### 6. Subagent 和 provider 收口

- legacy `delegate` 改为 `SubagentManager.spawn(..., subagent_type="Explore", background=False)` 的兼容包装
- 外部工具结果仍返回 `delegate_result`
- session subagent 记录与普通 Explore subagent 走同一通知路径
- 新增 `pico/providers/base.py::CompletionResult`
- `_complete_model_turn()` 兼容 provider 返回 `CompletionResult(text, metadata)`

## 关键修正

Reviewer 发现 ToolRunner callback 外移后，`partial_success` / `error` 也会更新 memory/read ledger。已修正：

- 只有 `tool_status == "ok"` 才更新 memory 和 read ledger
- `partial_success` 仍会记录 process note，保留探索价值
- 新增回归测试覆盖 `write_files` 部分成功时不会把未写入路径记进 memory

## 当前结果

- `pico/core/agent.py`：约 2384 行，低于第一阶段 `<2400` gate
- `Pico.ask()`：约 79 行
- `RuntimeEngine`：约 444 行
- 全量测试：`278 passed, 6 warnings`
- lint：`uv run ruff check .` 通过

## 仍然保留的边界

这轮没有假装已经完成生产级 runtime：

- reducer 还没有覆盖所有 state mutation，例如 completion gate、verification、checkpoint id 仍有部分直接写入
- TUI 已经有 `RuntimeSnapshot`，但 slash command 还没有完全迁到独立 command bus
- provider 已有 typed `CompletionResult` 兼容入口，但 `clients.py` 还没有按 provider 拆文件
- evaluator/metrics 的定位仍应描述为 deterministic harness regression，不应说成泛化 coding benchmark

下一步如果继续做，优先级是：把剩余 state mutation 接入 `RunEvent`，再把 TUI slash command 全部改成 command bus。
