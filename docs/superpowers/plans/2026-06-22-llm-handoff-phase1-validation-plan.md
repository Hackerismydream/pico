# LLM Handoff Context Compaction — Phase 1 Validation Plan

## 目标

Phase 1 代码已合并，单元测试全绿。本计划的目标是补一层**端到端 runtime 验证**：用自动化脚本模拟真实多轮 session，证明 LLM handoff compaction 在 runtime 层面正确触发、正确回退、正确记账。

这不是重复单元测试，而是验证组件在 runtime pipeline 中组合后的行为。

---

## 交付物

创建一个脚本和一组 acceptance test：

| 文件 | 用途 |
|------|------|
| `scripts/validate_llm_handoff.py` | 端到端验证脚本，可独立运行，输出 PASS/FAIL |
| `tests/test_llm_handoff_e2e.py` | pytest acceptance test（同样逻辑，纳入 CI） |

---

## 验证场景

### Scenario 1: tier3 主动触发 LLM handoff（happy path）

**设置：**
- `ScriptedModelClient` 配置 `context_window = 1000`
- 预填 6 轮对话（每轮 user 900 chars + assistant 900 chars = ~10800 chars total → ~2700 tokens）
- 压力比 = 2700 / 1000 = 2.7 → 远超 0.95 → tier3_summary
- char budget 设为 60000（默认），所以 10800 chars 不会触发 `prompt_over_budget`
- ScriptedModelClient 的 responses 列表需要包含**两个**响应：
  1. 第一个：handoff compact call 的 LLM 输出（结构化 markdown）
  2. 第二个：主 turn 的模型输出（正常助手回复）
- 设置 `last_completion_metadata` 模拟前一次真实调用的 token 信息

**验证点：**
1. `context_orchestrator_decision` event 中 `compact_trigger == "auto_tier3_summary"`
2. `summary_mode == "llm"`（不是 deterministic）
3. session 中 `history[0].kind == "compact_summary"` 且内容包含 `## Goal` 和 `## Next Steps`
4. `compact_call_usage` 不为 None，且 `input_tokens > 0`、`output_tokens > 0`
5. `compact_call_usage` **不在** `session["compactions"][-1]` 中（不持久化）
6. 主 turn 正常完成（最终有 assistant 回复）

**ScriptedModelClient 的 handoff LLM 输出示例：**
```
## Goal
Implement authentication middleware for the Express app

## Files Read
- src/middleware/auth.js
- src/config/jwt.js

## Files Modified
- src/middleware/auth.js

## Key Decisions
- Use RS256 for JWT signing instead of HS256

## Next Steps
- Add token refresh endpoint
- Write integration tests for auth flow
```

### Scenario 2: LLM 失败 → deterministic fallback

**设置：**
- 同 Scenario 1 的 history 和 pressure 设置
- ScriptedModelClient 的第一个响应设为 `raise Exception("model error")` 或返回无法解析的乱文本（如 `"sorry I cannot help"`）
- 第二个响应为正常助手回复

**验证点：**
1. `compact_trigger == "auto_tier3_summary"`（触发了）
2. `summary_mode == "deterministic_fallback"`
3. session history 仍有 `compact_summary`，但内容是 deterministic 格式（`"Compacted session summary:"` 开头）
4. 主 turn 正常完成（没有中断）
5. 如果 adapter.last_usage 存在，`compact_call_usage` 仍被记录（即使 parse 失败）

**实现方式 — ScriptedModelClient 返回无法解析的内容：**
```python
ScriptedModelClient([
    "I apologize but I cannot produce a summary in that format.",  # compact call → parse failure
    "<final>normal response</final>",  # main turn
])
```

HandoffAdapter 检查 `if not summary.goal or not summary.next_steps: return None`，因此上面的输出会触发 fallback。

### Scenario 3: 低压不触发任何 compaction

**设置：**
- `context_window = 200000`（默认大窗口）
- 预填 2 轮短对话（每轮 100 chars）
- 压力比 ≈ 0.001 → tier0_observe

**验证点：**
1. `compact_trigger` is None
2. `summary_mode == ""`（没有 compact 发生）
3. session history 不含 `compact_summary` item
4. 没有 `compaction_created` event

### Scenario 4: prompt_over_budget 优先走 deterministic（不走 LLM）

**设置：**
- `context_window = 1000`（tier3 也满足）
- `total_budget = 5000`（char budget 设小，强制 `prompt_over_budget = True`）
- 预填 6 轮大对话

**验证点：**
1. `compact_trigger == "auto_prompt_over_budget"`（不是 tier3_summary）
2. `summary_mode == "deterministic"`
3. `compact_call_usage` is None（没有 LLM 调用）

### Scenario 5: delta 不足（< 4 events）不触发

**设置：**
- `context_window = 1000`
- 仅 1 轮对话 + 1 条 compact_summary（delta 只有 2 events）
- 压力比 > 0.95

**验证点：**
1. `compact_trigger` is None
2. `auto_compaction_skip_reason` 包含某种 skip 理由或 orchestrator 不触发

### Scenario 6: replacement ledger 在 LLM compact 后不被破坏

**设置：**
- 同 Scenario 1
- compact 前在 session 中预设 `context_replacements = {"event_abc": {"event_id": "event_abc", "content_sha256": "xxx", ...}}`

**验证点：**
1. compact 后 `session["context_replacements"]` 仍存在且内容不变
2. ledger 没有被清空或覆盖

### Scenario 7: 净收益计算（正收益 vs 负收益）

**设置 — 正收益：**
- pre_compact_estimated_tokens = 2700
- post_compact_estimated_tokens = 500
- compact_call_usage.total_tokens = 200
- 净收益 = 2700 - 500 - 200 = 2000（正）

**设置 — 负收益：**
- pre_compact_estimated_tokens = 1000
- post_compact_estimated_tokens = 900
- compact_call_usage.total_tokens = 500
- 净收益 = 1000 - 900 - 500 = -400（负，正常暴露）

**验证点：**
1. budget summary 中 `compact_net_benefit_tokens` 值正确
2. 负收益不被 clamp 到 0

---

## 实现指南

### `scripts/validate_llm_handoff.py` 结构

```python
#!/usr/bin/env python3
"""End-to-end validation of LLM Handoff Context Compaction Phase 1."""

import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient


def scenario_1_tier3_triggers_llm_handoff():
    """tier3_summary triggers LLM handoff compaction."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # LLM compact response + main turn response
        handoff_output = """## Goal
Implement authentication middleware

## Files Read
- src/auth.js

## Files Modified
- src/auth.js

## Key Decisions
- Use RS256 for JWT

## Next Steps
- Add token refresh endpoint
"""
        client = ScriptedModelClient([
            handoff_output,
            "<final>Done, auth middleware is ready.</final>",
        ])
        client.context_window = 1000
        client.last_completion_metadata = {
            "input_tokens": 950,
            "output_tokens": 50,
            "total_tokens": 1000,
            "cached_tokens": 0,
            "provider_protocol": "openai",
            "provider_model": "test-model",
            "provider_base_url": "http://localhost",
        }

        agent = Pico(
            model_client=client,
            workspace=WorkspaceContext.build(tmp_path),
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            approval_policy="auto",
        )

        # Pre-fill history to reach tier3
        for i in range(6):
            agent.record({"role": "user", "content": f"request {i} " + "x" * 900})
            agent.record({"role": "assistant", "content": f"answer {i} " + "y" * 900})

        # Run a turn — should trigger tier3 → LLM compact
        events = list(agent.engine.run_turn("finish the auth work"))

        # Assertions
        session = agent.session
        history = session.get("history", [])

        # 1. compact_summary exists with structured content
        summaries = [h for h in history if h.get("kind") == "compact_summary"]
        assert summaries, "FAIL: No compact_summary in history"
        assert "## Goal" in summaries[0]["content"], "FAIL: Summary missing ## Goal"
        assert "## Next Steps" in summaries[0]["content"], "FAIL: Summary missing ## Next Steps"

        # 2. Check events for correct trigger
        # (Read from session_event_bus or check metadata in last orchestrator decision)

        # 3. compact_call_usage not persisted
        compactions = session.get("compactions", [])
        if compactions:
            assert "compact_call_usage" not in compactions[-1], \
                "FAIL: compact_call_usage leaked into persistent compactions"

        print("PASS: Scenario 1 — tier3 triggers LLM handoff")


def scenario_2_llm_failure_fallback():
    """LLM failure falls back to deterministic."""
    # ... similar setup but ScriptedModelClient returns unparseable text ...
    print("PASS: Scenario 2 — LLM failure falls back to deterministic")


def scenario_3_low_pressure_no_compact():
    """Low pressure does not trigger compaction."""
    # ... small history, large context_window ...
    print("PASS: Scenario 3 — low pressure no compact")


# ... scenarios 4-7 ...


def main():
    scenarios = [
        scenario_1_tier3_triggers_llm_handoff,
        scenario_2_llm_failure_fallback,
        scenario_3_low_pressure_no_compact,
        # scenario_4_prompt_over_budget_deterministic,
        # scenario_5_insufficient_delta,
        # scenario_6_replacement_ledger_preserved,
        # scenario_7_net_benefit_calculation,
    ]

    failures = []
    for fn in scenarios:
        try:
            fn()
        except AssertionError as e:
            failures.append(f"{fn.__name__}: {e}")
            print(f"FAIL: {fn.__name__}: {e}")
        except Exception as e:
            failures.append(f"{fn.__name__}: UNEXPECTED {type(e).__name__}: {e}")
            print(f"ERROR: {fn.__name__}: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {len(scenarios) - len(failures)}/{len(scenarios)} passed")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All scenarios passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

### `tests/test_llm_handoff_e2e.py` 结构

把上述场景转为 pytest 形式：

```python
"""End-to-end acceptance tests for LLM handoff context compaction."""

import pytest
from pathlib import Path
from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient


HANDOFF_LLM_OUTPUT = """## Goal
Implement authentication middleware

## Files Read
- src/auth.js

## Key Decisions
- Use RS256

## Next Steps
- Add refresh endpoint
"""


def _build_agent(tmp_path, responses, context_window=1000, total_budget=60000):
    """Build agent with scripted model and pre-filled history."""
    client = ScriptedModelClient(responses)
    client.context_window = context_window
    client.last_completion_metadata = {
        "input_tokens": 950,
        "output_tokens": 50,
        "total_tokens": 1000,
        "cached_tokens": 0,
        "provider_protocol": "openai",
        "provider_model": "test-model",
        "provider_base_url": "http://localhost",
    }
    agent = Pico(
        model_client=client,
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
    )
    if total_budget != 60000:
        agent.context_manager.total_budget = total_budget
    return agent


def _fill_history(agent, rounds=6, chars_per_message=900):
    """Add large history to push pressure above tier3."""
    for i in range(rounds):
        agent.record({"role": "user", "content": f"request {i} " + "x" * chars_per_message})
        agent.record({"role": "assistant", "content": f"answer {i} " + "y" * chars_per_message})


class TestTier3TriggersLlmHandoff:
    def test_compact_summary_has_structured_content(self, tmp_path):
        agent = _build_agent(tmp_path, [HANDOFF_LLM_OUTPUT, "<final>done</final>"])
        _fill_history(agent)
        list(agent.engine.run_turn("finish"))
        summaries = [h for h in agent.session["history"] if h.get("kind") == "compact_summary"]
        assert summaries
        assert "## Goal" in summaries[0]["content"]
        assert "## Next Steps" in summaries[0]["content"]

    def test_compact_trigger_is_tier3(self, tmp_path):
        # Check via session events or orchestrator metadata
        pass

    def test_compact_call_usage_not_persisted(self, tmp_path):
        agent = _build_agent(tmp_path, [HANDOFF_LLM_OUTPUT, "<final>done</final>"])
        _fill_history(agent)
        list(agent.engine.run_turn("finish"))
        compactions = agent.session.get("compactions", [])
        for c in compactions:
            assert "compact_call_usage" not in c


class TestLlmFailureFallback:
    def test_unparseable_output_falls_back(self, tmp_path):
        agent = _build_agent(tmp_path, [
            "Sorry, I can't help with that.",  # Compact call returns garbage
            "<final>done</final>",             # Main turn
        ])
        _fill_history(agent)
        list(agent.engine.run_turn("finish"))
        summaries = [h for h in agent.session["history"] if h.get("kind") == "compact_summary"]
        assert summaries
        assert summaries[0]["content"].startswith("Compacted session summary:")

    def test_main_turn_still_completes(self, tmp_path):
        agent = _build_agent(tmp_path, [
            "unparseable garbage xyz",
            "<final>all good</final>",
        ])
        _fill_history(agent)
        events = list(agent.engine.run_turn("finish"))
        # Should not raise; agent should produce a response
        assert any("all good" in str(e) for e in events) or True  # Adapt to event structure


class TestLowPressureNoCompact:
    def test_no_compaction_at_tier0(self, tmp_path):
        agent = _build_agent(tmp_path, ["<final>response</final>"], context_window=200000)
        agent.record({"role": "user", "content": "short"})
        agent.record({"role": "assistant", "content": "short"})
        list(agent.engine.run_turn("hi"))
        summaries = [h for h in agent.session["history"] if h.get("kind") == "compact_summary"]
        assert not summaries


class TestPromptOverBudgetDeterministic:
    def test_over_budget_uses_deterministic(self, tmp_path):
        agent = _build_agent(tmp_path, ["<final>done</final>"], total_budget=5000)
        _fill_history(agent)
        list(agent.engine.run_turn("finish"))
        summaries = [h for h in agent.session["history"] if h.get("kind") == "compact_summary"]
        if summaries:
            # Should be deterministic, not structured handoff
            assert summaries[0]["content"].startswith("Compacted session summary:")


class TestReplacementLedgerPreserved:
    def test_ledger_survives_llm_compact(self, tmp_path):
        agent = _build_agent(tmp_path, [HANDOFF_LLM_OUTPUT, "<final>done</final>"])
        # Pre-set ledger
        agent.session["context_replacements"] = {
            "event_abc": {
                "event_id": "event_abc",
                "content_sha256": "deadbeef",
                "replacement_text": "stub",
                "saved_chars": 100,
            }
        }
        _fill_history(agent)
        list(agent.engine.run_turn("finish"))
        assert "event_abc" in agent.session.get("context_replacements", {})


class TestNetBenefitCalculation:
    def test_positive_net_benefit(self, tmp_path):
        # Needs access to budget_summary from metadata — check events or report
        pass

    def test_negative_net_benefit_not_clamped(self, tmp_path):
        # Same structure, verify negative value is preserved
        pass
```

---

## 实现约束

1. **不改任何 Phase 1 代码。** 这是纯验证层，只新增脚本和测试文件。
2. **使用 `ScriptedModelClient`。** 不依赖真实 API key。参考 `tests/test_context_orchestrator_acceptance.py` 中的模式。
3. **ScriptedModelClient 需要支持多次调用。** compact call 消耗第一个 response，主 turn 消耗第二个。确认 `ScriptedModelClient` 是按顺序消费 responses 列表的（它已经是这样工作的）。
4. **不修改 CI 配置。** 新测试放在 `tests/` 下，已有 `pytest tests/` 会自动发现。
5. **脚本可独立运行：** `uv run python scripts/validate_llm_handoff.py` 输出 PASS/FAIL，退出码 0/1。
6. **所有 assertion 要有清晰的错误消息。** 不要裸 assert。

---

## 访问 orchestrator 决策 metadata 的方式

在 runtime 执行后，获取 compact 相关元数据有两种方式：

### 方式 A：读 session event bus

```python
import json
events_path = agent.session_event_bus.path
with open(events_path) as f:
    events = [json.loads(line) for line in f]
decisions = [e for e in events if e.get("event") == "context_orchestrator_decision"]
```

### 方式 B：读 run trace

```python
trace_path = agent.current_run_dir / "trace.jsonl"
# Similar parsing
```

### 方式 C：Hook into event bus before run

```python
captured = []
agent.session_event_bus.on("context_orchestrator_decision", captured.append)
list(agent.engine.run_turn("finish"))
# Now captured[0] has the decision metadata
```

选择 **方式 C** 最适合测试——不需要文件 I/O，直接内存断言。

---

## 执行顺序

1. 先读 `pico/testing.py` 确认 `ScriptedModelClient` 的接口（responses 列表、context_window 属性、last_completion_metadata、how it handles multiple calls）。
2. 读 `tests/test_context_orchestrator_acceptance.py` 作为参考模式。
3. 创建 `scripts/validate_llm_handoff.py`，实现全部 7 个场景。
4. 运行 `uv run python scripts/validate_llm_handoff.py`，确认全部 PASS。
5. 创建 `tests/test_llm_handoff_e2e.py`，将场景转为 pytest。
6. 运行 `uv run pytest -q tests/test_llm_handoff_e2e.py`，确认全部 PASS。
7. 运行 `uv run pytest -q tests/` 全量，确认无回归。

---

## 验收标准

全部通过后回答这四个问题（对应 scope note 的判断标准）：

| 问题 | 通过条件 |
|------|----------|
| 高压时是否主动生成 handoff summary？ | Scenario 1 PASS |
| LLM 失败时是否不影响主任务？ | Scenario 2 PASS |
| compact token/cost 是否被算进净收益？ | Scenario 7 PASS |
| 旧上下文治理能力是否没有回退？ | Scenarios 3/4/5/6 PASS |
