# Claude Code Review Brief: LLM Handoff Context Compaction Phase 1

请 review 这次 Phase 1 实现，不要修改代码。

## 背景

Pico 的上下文治理已经有 deterministic 层：context budget、pressure tier、history retention/replacement、deterministic compact、trace/report/budget summary。

这次改动的目标不是替换现有系统，而是在高压阶段补一层 LLM handoff compaction：

- 低压和 hard over-budget 默认路径保持 deterministic；
- 当 `context_usage.pressure_tier == "tier3_summary"` 且 delta history 足够时，主动调用 LLM 生成 handoff summary；
- LLM 失败、解析失败、usage metadata 异常时，都不能中断主任务，必须回退 deterministic compact；
- compact call 自己的 token usage 单独记录，并用于计算净收益；
- Phase 1 不做 `/compact --llm` UI、不做 final readiness 新 reason、不做完整 retention decision taxonomy。

## 主要改动

### 1. Handoff adapter

新增：

- `pico/core/context_handoff.py`
- `tests/test_context_handoff.py`

实现内容：

- `HandoffSummary`
- `HandoffParser`
- `HandoffAdapter`
- `render_handoff_summary`
- `render_delta_for_handoff`

关键点：

- 通过 `pico.providers.base.complete_model(...)` 调模型，不直接调用 `model_client.complete(...)`。
- `Goal` 和 `Next Steps` 是 required section，缺失时返回 `None`，由 compact 层 fallback。
- usage metadata 经过安全整数归一化，非数字和负数都归零，避免 provider usage 异常打断 compact。

### 2. CompactManager summary mode

修改：

- `pico/core/compact.py`
- `pico/core/runtime.py`
- `tests/test_compact.py`

实现内容：

- `compact_history(..., summary_mode="deterministic")` 透传到 `CompactManager.compact(...)`。
- `summary_mode="llm"` 且存在 delta 时，调用 `HandoffAdapter`。
- LLM success：把 structured handoff summary 存成 `compact_summary`。
- LLM failure / parse failure：回退 `_summary_text(...)`，`summary_mode="deterministic_fallback"`。
- `compact_call_usage` 保留在 compact 返回值和 `compaction_created` event 里，但不会持久化到 `session["compactions"]`。

### 3. Tier3 proactive trigger

修改：

- `pico/core/context_usage.py`
- `pico/core/context_orchestrator.py`
- `tests/test_context_orchestrator.py`

实现内容：

- `ContextUsageAnalyzer` 读取 `model_client.context_window`，便于真实模型窗口和测试窗口影响 pressure tier。
- `ContextOrchestrator` 新增 proactive tier3 path：
  - `prompt_over_budget` 优先：`auto_prompt_over_budget` + deterministic；
  - 非 over-budget 且 `tier3_summary` + delta >= 4：`auto_tier3_summary` + llm；
  - delta < 4：不 compact。

### 4. Budget summary usage / net benefit

修改：

- `pico/core/context_budget_summary.py`
- `tests/test_context_budget_summary.py`
- `tests/test_context_orchestrator_acceptance.py`

实现内容：

- `context_orchestrator` metadata 透出：
  - `summary_mode`
  - `compact_call_usage`
  - `pre_compact_estimated_tokens`
  - `post_compact_estimated_tokens`
- `context_budget_summary` 计算：
  - `compact_call_usage`
  - `compact_net_benefit_tokens = pre - post - compact_total_tokens`
- 允许负收益，不 clamp，这样能暴露 LLM compact 花费超过主请求节省的情况。

## Review 重点

请重点看：

1. `tier3_summary` 主动触发是否真的不是 over-budget 后补救。
2. `prompt_over_budget + tier3_summary` 同时成立时，hard budget 优先 deterministic 是否合理。
3. LLM failure / parse failure / bad usage metadata 是否都不会破坏主流程。
4. `compact_call_usage` 是否既能被 report/evidence 使用，又不会持久化污染 session。
5. `compact_net_benefit_tokens` 的计算是否足够诚实，尤其负收益场景。
6. `context_handoff.py` 是否承担了 prompt/parser/provider adapter 职责，避免把逻辑塞回 `compact.py`。
7. architecture budget 更新是否合理，有没有掩盖模块膨胀。

## 已验证

最后一次全量测试：

```bash
uv run pytest -q tests
```

结果：

```text
421 passed, 2 skipped, 6 warnings
```

Focused gate：

```bash
uv run pytest -q \
  tests/test_context_handoff.py \
  tests/test_compact.py \
  tests/test_context_orchestrator.py \
  tests/test_context_orchestrator_acceptance.py \
  tests/test_context_budget_summary.py \
  tests/test_architecture_boundaries.py
```

结果：

```text
30 passed
```

## 已知边界

- 当前工作区在这次改动前已经有大量上下文治理相关未提交文件，本次提交只 stage Phase 1 相关文件。
- Phase 1 没有实现 `/compact --llm` CLI。
- Phase 1 没有把 compact model call 拆成单独 trace event；usage 目前通过 compact summary / orchestrator metadata / budget summary 暴露。
- Phase 1 没有扩展 live provider benchmark，只保证 runtime contract 和测试闭环。
