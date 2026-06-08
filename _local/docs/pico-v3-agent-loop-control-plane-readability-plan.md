# Pico v3 Agent Loop Control Plane 可读性收口方案

日期：2026-06-08

分支：`codex/v3-agent-loop-control-plane`

基线提交：`00ff8ab Harden agent loop control plane`

状态：实施前方案

## 目标

这轮不是继续改架构，也不是再加一层新功能。上一轮 hardening 已经把
agent loop control plane 的关键正确性问题处理掉了，现在要做的是收口：
让代码读起来像一个已经稳定下来的 runtime control plane，而不是一组刚
堆完的功能点。

主方向保持不变：

```text
emit_trace -> runtime consumers -> TaskState summaries -> report/final readiness
```

`Engine.run_turn()` 仍然保持线性 generator loop，不改成完整状态机。我们要
做的是把命名、字符串协议、helper 边界、evidence schema 和测试组织收稳。

## 当前判断

GPT Pro review 里的 P0 正确性问题已经基本吸收：

- `run_shell` 的状态从完整 `full_result` 解析，不再依赖 clipped observation。
- runtime consumer 异常会进入 `TaskState.evidence_summaries`，不会静默消失。
- strict final readiness 只阻断 hard reason。
- `partial_success + workspace_changed` 已经是 hard readiness reason。
- 长工具输出 artifact 支持 workspace 外部的 run store。
- verification command 不再用 substring 判断，已经升级成 command classifier。
- microcompact 保留 recent、last failed、last workspace-changing、以及命中当前
  changed paths 的旧工具结果。
- provider retry、parse retry、plan notice、strict final gate、retry limit、
  step limit、多工具 requested/executed count 都已有 stream/transition 覆盖。

剩下的问题不是架构方向错，而是代码边界还不够利落：

- `Engine.run_turn()` 调用 transition 时还在传裸字符串。
- `final_readiness.py` 里 reason code、severity、notice 文案还没有 catalog 化。
- `tool_executor.py` 多个分支重复手写 `_last_tool_result_metadata`。
- `tool_result_artifacts.py` 的函数名像 render，但实际还负责 artifact 持久化和
  metadata 构造。
- `governance_decision` 只有稳定 reason code，不够保留底层来源。
- `evidence_summaries` 没有 schema version。
- `tests/test_engine_acceptance.py` 已经开始承担太多规格面。

## 非目标

- 不接 Langfuse，不引入外部 observability sink。
- 不把 `Engine.run_turn()` 改成状态机。
- 不改变用户可见 stream event 顺序。
- 不让 `build_report()` 反扫 `trace.jsonl`。
- 不在 microcompact 时修改 `session["history"]`。
- 不改变 final readiness 默认模式。
- 不处理无关的 `_local/benchmark`、`_local/research`、`_local/worktrees`、
  `examples` 和 release assets。

## 方案立场

下一轮最好是一个纯 refinement commit，主题可以是：

```text
refactor(runtime): clarify loop control-plane boundaries
```

这个 commit 不应该增加用户可见能力。它的价值是让现在已经跑通的 control
plane 更容易 review，也更不依赖散落的字符串和重复 dict。

## Phase 1：稳定 runtime vocabulary

### 1. transition 调用点改用常量和薄 wrapper

`turn_transitions.py` 已经定义 reason 常量，但 `engine.py` 和 helper 里仍然有：

```python
emit_transition(agent, task_state, kind="continue", reason="provider_retry")
```

改成：

```python
emit_continue_transition(agent, task_state, CONTINUE_PROVIDER_RETRY)
```

新增两个薄 wrapper：

```python
emit_continue_transition(...)
emit_terminal_transition(...)
```

这样 `engine.py` 里读到的是控制流语义，不是底层 event 构造细节。

验收标准：

- runtime 行为不变。
- 现有 transition 测试继续通过。
- 新测试确认 engine 路径仍发出相同 reason code。
- `turn_transitions.py` 仍在架构预算内；如果必须涨预算，需要明确说明是因为
  reason vocabulary 归口到了这个模块。

### 2. 明确 `turn_index` 和 `attempt_index` 的关系

现在两个字段都来自 `task_state.attempts`。如果它们没有真实区别，就不要同时
暴露。建议：

- 保留 `attempt_index`，表示当前 run 内第几次模型调用。
- 删除新 transition payload 里的 `turn_index`，除非后面真的有 run 内 turn 的
  独立概念。

验收标准：

- transition summary 测试覆盖最终保留的字段。
- report 不再出现两个值永远相同、但语义不清的计数字段。

### 3. evidence summaries 加 schema version

给会被 report 或外部消费者读取的 summary 加版本字段：

```json
{
  "schema_version": "pico.transition_summary.v1"
}
```

先覆盖这些 summary：

- `transition_summary`
- `context_budget_summary`
- `governance_summary`
- `verification_signal`
- `final_readiness_summary`

`context_budget_summary` 额外加：

```json
{
  "budget_unit": "tokens_estimated",
  "token_estimator": "context_usage_analyzer"
}
```

验收标准：

- report 里每类 summary 都有 schema version。
- 测试断言这些版本字段。
- `build_report()` 仍然只 snapshot `TaskState`，不解析 raw trace。

## Phase 2：让 final readiness 自己解释清楚

### 1. 把 reason 升级成 catalog

当前 `final_readiness.py` 有 `HARD_REASONS`，`_readiness_reasons()` 里也直接 append
裸字符串。下一步改成一个集中 catalog：

```python
READINESS_REASONS = {
    "partial_success_workspace_changed": {
        "severity": "hard",
        "message": "a tool partially succeeded and changed the workspace",
    },
}
```

对外仍然可以返回 `reasons` code，保持 trace/report 兼容；severity 和 notice 文案
从 catalog 派生。

验收标准：

- strict 模式仍然只 block hard reason。
- warn/soft 模式行为不变。
- 测试覆盖至少一个 hard reason 和一个 soft reason。
- reason code 稳定，不因为改文案而变化。

### 2. runtime notice 用人能读懂的文案

现在 notice 会直接暴露内部 reason code，比如：

```text
changed_paths_without_verification
```

reason code 应该保留在 trace/report 里，runtime notice 则应该告诉模型要处理什么：

```text
Before final answer, address this runtime readiness issue:
- Files changed, but no successful verification was recorded.
Return final again only after verifying, or explicitly explain why verification
is not available.
```

验收标准：

- trace/report 仍然有机器可读 reason code。
- runtime notice 使用 catalog message。
- final gate block 文案保持简短，不把内部实现细节全塞给用户。

## Phase 3：集中 tool outcome metadata

### 1. 抽出 tool metadata builder

`tool_executor.py` 现在在 unknown tool、invalid args、repeated call、permission
deny、policy deny、success、exception 分支里重复构造 metadata dict。这个 dict 是
memory、checkpoint、governance、verification、final readiness 的共同输入，不能靠
复制粘贴维持一致。

新增一个小 helper：

```python
tool_result_metadata(...)
```

如果 dataclass 读起来更清楚，也可以做轻量 `ToolOutcome`。它需要统一负责这些字段：

- `tool_status`
- `tool_error_code`
- `security_event_type`
- `risk_level`
- `read_only`
- `affected_paths`
- `workspace_changed`
- `workspace_fingerprint`
- `diff_summary`
- artifact metadata

验收标准：

- `tool_executor.py` 的所有分支行为不变。
- governance、verification、process note、history item、final readiness 仍能拿到
  同样字段。
- focused tests 覆盖 invalid args、permission deny、policy deny、shell error、
  shell partial success、长输出 artifact metadata。

### 2. 重命名 tool result observation 准备函数

`render_tool_result()` 不只是 render。它会判断输出是否过长、写 artifact、返回给模型
看的 observation，并构造 metadata。名字应该改成：

```python
prepare_tool_result_observation()
```

优先一次性改完所有调用点，不留长期 alias。

验收标准：

- `tool_executor.py` 的阅读顺序变成：
  - 执行真实工具；
  - 解释真实结果；
  - 准备模型 observation；
  - 持久化 metadata。
- 长输出 artifact 相关测试继续通过。

### 3. artifact ref 归 `RunStore` 管

当前 fallback 已经能工作，但 artifact ref 的语义仍在 `tool_result_artifacts.py`
里判断。更清楚的边界是让 `RunStore` 提供：

```python
RunStore.artifact_ref(task_state, path)
```

这样 artifact 是 run-store 概念，不需要 tool result 层猜路径相对谁。

验收标准：

- workspace 外部 run-store 的 artifact 测试继续通过。
- artifact ref 稳定、可恢复。
- 正常 report 不泄漏本地绝对路径。

## Phase 4：增强 governance evidence

### 1. 保留底层原始 reason

`governance_decision.reason_code` 继续作为稳定归因口径，但 event 里要保留底层来源：

```json
{
  "reason_code": "read_only_violation",
  "original_reason": "tool_not_allowed",
  "security_event_type": "read_only_block",
  "effects": []
}
```

这样 read-only profile deny、tool policy deny、sandbox unavailable 这些路径都能同时
解释稳定分类和底层来源。

验收标准：

- 现有 governance reason 测试继续通过。
- 新测试至少覆盖 permission deny 和 policy deny 的 `original_reason`。
- 不突破现有 redaction 边界。

### 2. governance summary 加 decision type counts

`reduce_governance_summary()` 增加：

```json
{
  "decision_type_counts": {
    "tool_validation": 1,
    "permission": 1,
    "tool_policy": 1
  }
}
```

验收标准：

- report 能区分 validation、permission、policy、sandbox、repetition 等失败层。
- `deny_count` 继续保留，兼容旧消费者。

### 3. 标记 critical runtime consumer

给 `EvidenceSummaryConsumer` 增加轻量标记：

```python
critical = True
```

Artifact graph 和 verifier suggestion 失败可以降级；Evidence summary 失败会削弱
control plane，应该更容易被看见。

建议行为：

- 所有 consumer error 都记录。
- critical consumer error 继续进入 `evidence_summaries.consumer_errors`。
- 这一轮不打断用户 stream。

验收标准：

- duplicate terminal transition 仍然产生可见 consumer error。
- 正常 run 不包含 consumer error。
- 测试能区分 critical 和 non-critical consumer failure。

## Phase 5：把 microcompact retention policy 抽出来

`TurnHistoryBuilder._compressed_turn_entries()` 现在把策略和渲染混在一起。抽一个很小的
retention context：

```python
HistoryRetentionContext
```

再抽一个 policy helper：

```python
should_render_tool_inline(item, context)
```

它需要保留：

- recent turns；
- last failed tool result；
- last workspace-changing tool result；
- touch 当前 changed paths 的工具结果。

验收标准：

- prompt rendering 仍然不修改 `session["history"]`。
- 现有 microcompact 测试继续通过。
- changed-path retention 有 focused test。
- `turn_history.py` 仍低于架构预算。

## Phase 6：拆分测试规格面

`tests/test_engine_acceptance.py` 已经太宽。不要大规模重写，只把明显聚焦的测试挪出去：

```text
tests/test_engine_stream.py
tests/test_engine_transitions.py
tests/test_final_readiness_acceptance.py
tests/test_tool_result_artifacts.py
```

如果能减少重复读 report/trace，可以加一个小 helper：

```python
run_and_read_evidence(agent, request)
```

验收标准：

- 测试名仍然描述行为。
- 不删覆盖。
- full suite 继续绿。

## Phase 7：可选的文件边界整理

这一步有价值，但不是正式 PR 前的硬门槛。

### 1. 按职责拆 `engine_helpers.py`

现在 `engine_helpers.py` 同时放了工具执行、final readiness、successful/stopped/limited
finish path、step-limit summary、retry 判断、memory maintenance safety。它已经不是普通
helper 文件。

可选拆分：

```text
pico/core/engine_tools.py
pico/core/finish_paths.py
pico/core/step_limit.py
```

只有前面 phases 都稳定后再做。这个阶段只做文件边界，不改行为。

### 2. 抽出 prompt-build side effects

如果 `run_turn()` 后续又变拥挤，再把 prompt build 后的 checkpoint/context-reduction
side effects 抽成：

```python
checkpoint_after_prompt_build(...)
```

主循环仍然保持：

```text
prompt -> model -> parse -> tools -> continue/final
```

## 推荐实施顺序

1. transition 常量/wrapper 和 evidence schema version。
2. final readiness reason catalog 和 notice 文案。
3. tool metadata builder 和 observation 函数重命名。
4. governance event detail 和 consumer criticality。
5. microcompact retention policy 抽取。
6. 测试文件拆分。
7. 可选拆 `engine_helpers.py`。

这个顺序先收协议，再收 metadata，再收测试和文件边界，避免一上来做纯搬文件导致 diff
很大、review 成本很高。

## 验证命令

每个 phase 后跑：

```bash
uv run pytest tests/test_turn_transitions.py tests/test_final_readiness.py tests/test_tool_policy_acceptance.py tests/test_engine_acceptance.py tests/test_architecture_boundaries.py -q
uv run ruff check pico tests scripts
git diff --check
```

最终跑：

```bash
uv run pytest tests -q
uv run ruff check pico tests scripts
git diff --check
```

上一轮 hardening 的基线是：

```text
319 passed, 2 skipped
```

现有 metrics UTC deprecation warnings 不属于这份 plan。

## 合入标准

这轮收口完成时，应该满足：

- `Engine.run_turn()` 仍然一眼能看出主循环。
- transition 和 readiness reason vocabulary 集中管理。
- evidence summaries 有版本。
- tool outcome metadata 只在一个地方构造。
- governance decision 能同时解释稳定分类和底层来源。
- microcompact retention policy 有名字、能单测。
- report 仍然只是 `TaskState` snapshot。
- 测试更像规格，不只是运行脚本。

