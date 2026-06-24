# LLM Handoff Context Compaction — Implementation Plan (Phase 1)

## Overview

This plan implements Phase 1 of LLM Handoff Context Compaction as defined in [the scope note](./2026-06-22-llm-handoff-context-compaction-scope-note.md).

Goal: When context pressure reaches `tier3_summary`, use an LLM call to generate a structured handoff summary instead of the current deterministic text-only compaction. If the LLM call fails, fall back to deterministic mode transparently.

## Architecture Context

Current data flow:
```
ContextOrchestrator.build(snapshot)
  → ContextManager.build(user_message)
  → ContextUsageAnalyzer.analyze(rendered) → pressure_tier
  → if prompt_over_budget: CompactManager.compact() [deterministic]
  → rebuild prompt
```

Target data flow:
```
ContextOrchestrator.build(snapshot)
  → ContextManager.build(user_message)
  → ContextUsageAnalyzer.analyze(rendered) → pressure_tier
  → if tier3_summary AND sufficient delta:
      CompactManager.compact(summary_mode="llm")
        → HandoffAdapter.generate(delta, prior_summary)
          → complete_model(...) [records own usage]
          → HandoffParser.parse(raw_text) → HandoffSummary
        → on failure: fallback to deterministic
  → rebuild prompt
```

## File Plan

### New Files

| File | Purpose |
|------|---------|
| `pico/core/context_handoff.py` | HandoffAdapter, HandoffParser, HandoffSummary dataclass, prompt template |
| `tests/test_context_handoff.py` | Unit tests for parser, adapter, fallback |
| `tests/test_llm_compaction_integration.py` | Integration tests: tier3 trigger, old session compat, ledger no-drift |

### Modified Files

| File | Change |
|------|--------|
| `pico/core/compact.py` | Add `summary_mode` param to `compact()`; call HandoffAdapter when mode="llm"; record compact_usage |
| `pico/core/context_orchestrator.py` | Trigger LLM compaction on `tier3_summary` with sufficient delta (not just `prompt_over_budget`) |
| `pico/core/context_budget_summary.py` | Add `compact_call_usage` field to budget summary schema |
| `pico/core/context_report.py` | Surface `compact_call_usage` in report metadata |

---

## Step 1: `pico/core/context_handoff.py` — New Module

Create a new module with three components:

### 1.1 `HandoffSummary` dataclass

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class HandoffSummary:
    """Structured summary produced by the LLM handoff compactor."""
    goal: str                          # What the user is trying to accomplish
    constraints: tuple[str, ...] = ()  # User-stated constraints and preferences
    files_read: tuple[str, ...] = ()   # File paths read during summarized turns
    files_modified: tuple[str, ...] = ()  # File paths modified
    key_decisions: tuple[str, ...] = ()   # Important decisions made
    blockers: tuple[str, ...] = ()     # Current blockers or open questions
    next_steps: tuple[str, ...] = ()   # What the agent should do next
    raw_text: str = ""                 # Full LLM output (for fallback rendering)
```

### 1.2 `HANDOFF_PROMPT_TEMPLATE`

A prompt template that instructs the LLM to produce a structured summary. The prompt:

```python
HANDOFF_PROMPT_TEMPLATE = """\
You are a context compactor for a coding agent. Your job is to produce a structured \
handoff summary so the agent can continue its task without re-reading the full history.

Below is the conversation delta (events since the last compaction) and optionally a \
prior summary. Produce a handoff summary in the following format exactly:

## Goal
<one sentence: what the user wants to accomplish>

## Constraints
- <user-stated constraint 1>
- <constraint 2>

## Files Read
- <path1>
- <path2>

## Files Modified
- <path1>
- <path2>

## Key Decisions
- <decision 1>
- <decision 2>

## Blockers
- <blocker or open question, if any>

## Next Steps
- <what the agent should do next>

Rules:
- Keep each section concise. Omit a section entirely if empty (except Goal and Next Steps which are required).
- Preserve exact file paths, variable names, error messages, and test names — these are critical for the agent.
- Do NOT add commentary or explanation outside the sections.
- If there is a prior summary, merge its content into your output rather than duplicating.

{prior_summary_block}

## Conversation Delta

{delta_text}
"""
```

Where `{prior_summary_block}` is either empty or:
```
## Prior Summary (merge into your output)

{prior_summary_text}
```

### 1.3 `HandoffParser`

```python
class HandoffParser:
    """Parses structured LLM output into HandoffSummary."""

    def parse(self, raw_text: str) -> HandoffSummary:
        """
        Parse the LLM's markdown output into a HandoffSummary.

        Strategy:
        - Split by ## headers
        - Extract bullet items from each section
        - If parsing fails (missing Goal or Next Steps), return a HandoffSummary
          with raw_text populated but structured fields empty — the caller decides
          whether to use raw_text as-is or fall back to deterministic.
        """
```

Implementation notes:
- Use simple string splitting on `\n## ` to find sections.
- Within each section, extract lines starting with `- ` as items.
- For `Goal`, take the first non-empty line after the header.
- Return `HandoffSummary` with all parsed fields.
- If `goal` is empty after parsing, set `goal = ""` — caller will detect this and may fall back.

### 1.4 `HandoffAdapter`

```python
from pico.providers.base import complete_model, ModelResult

class HandoffAdapter:
    """Generates a handoff summary via LLM call."""

    def __init__(self, model_client, max_summary_tokens=1024):
        self.model_client = model_client
        self.max_summary_tokens = max_summary_tokens
        self.parser = HandoffParser()
        self.last_usage = None  # Will hold usage dict after generate()

    def generate(self, delta_text: str, prior_summary_text: str = "") -> HandoffSummary | None:
        """
        Call the LLM to produce a handoff summary.

        Returns:
            HandoffSummary on success, None on failure (caller should fall back).

        Side effect:
            Sets self.last_usage = {
                "input_tokens": int,
                "output_tokens": int,
                "total_tokens": int,
                "cached_tokens": int,
                "model": str,
                "provider": str,
            }
        """
        prior_block = ""
        if prior_summary_text.strip():
            prior_block = f"## Prior Summary (merge into your output)\n\n{prior_summary_text}"

        prompt = HANDOFF_PROMPT_TEMPLATE.format(
            prior_summary_block=prior_block,
            delta_text=delta_text,
        )

        try:
            result: ModelResult = complete_model(
                self.model_client,
                prompt,
                self.max_summary_tokens,
            )
        except Exception:
            self.last_usage = None
            return None

        # Record usage from the compact call
        meta = result.metadata or {}
        self.last_usage = {
            "input_tokens": meta.get("input_tokens", 0),
            "output_tokens": meta.get("output_tokens", 0),
            "total_tokens": meta.get("total_tokens", 0),
            "cached_tokens": meta.get("cached_tokens", 0),
            "model": str(meta.get("provider_model", "")),
            "provider": str(meta.get("provider_protocol", "")),
        }

        summary = self.parser.parse(result.text)
        if not summary.goal:
            return None  # Parsing failed — caller falls back

        return summary
```

### 1.5 `render_handoff_summary(summary: HandoffSummary) -> str`

A helper that renders a `HandoffSummary` back into the text that gets stored in the session history as the `compact_summary` content:

```python
def render_handoff_summary(summary: HandoffSummary) -> str:
    """Render HandoffSummary to text for storage in session history."""
    lines = [f"## Goal\n{summary.goal}"]

    if summary.constraints:
        lines.append("\n## Constraints")
        lines.extend(f"- {c}" for c in summary.constraints)
    if summary.files_read:
        lines.append("\n## Files Read")
        lines.extend(f"- {f}" for f in summary.files_read)
    if summary.files_modified:
        lines.append("\n## Files Modified")
        lines.extend(f"- {f}" for f in summary.files_modified)
    if summary.key_decisions:
        lines.append("\n## Key Decisions")
        lines.extend(f"- {d}" for d in summary.key_decisions)
    if summary.blockers:
        lines.append("\n## Blockers")
        lines.extend(f"- {b}" for b in summary.blockers)
    if summary.next_steps:
        lines.append("\n## Next Steps")
        lines.extend(f"- {s}" for s in summary.next_steps)

    return "\n".join(lines)
```

---

## Step 2: Modify `pico/core/compact.py` — Add LLM Mode

### 2.1 Import the new module

```python
from pico.core.context_handoff import HandoffAdapter, render_handoff_summary
```

### 2.2 Add `summary_mode` parameter to `compact()`

Current signature:
```python
def compact(self, trigger="manual", keep_recent_turns=2):
```

New signature:
```python
def compact(self, trigger="manual", keep_recent_turns=2, summary_mode="deterministic"):
```

Where `summary_mode` is `"deterministic"` (current behavior) or `"llm"`.

### 2.3 LLM path inside `compact()`

After `plan()` confirms there are `delta_event_ids` (i.e., not a no-op), add a branch:

```python
compact_call_usage = None

if summary_mode == "llm":
    # Build delta text from delta_items (same items _summary_text uses)
    delta_text = self._render_delta_for_llm(delta_items)
    prior_text = (prior or {}).get("content", "") if prior else ""

    adapter = HandoffAdapter(
        model_client=self.agent.model_client,
        max_summary_tokens=1024,
    )
    handoff = adapter.generate(delta_text, prior_text)
    compact_call_usage = adapter.last_usage

    if handoff is not None:
        summary_text = render_handoff_summary(handoff)
    else:
        # Fallback to deterministic
        summary_text = self._summary_text(delta_items, prior_text)
        summary_mode = "deterministic_fallback"
else:
    summary_text = self._summary_text(delta_items, prior_text)
```

### 2.4 New helper: `_render_delta_for_llm(delta_items) -> str`

Renders the delta items into a text block suitable as LLM input. Similar to what `_summary_text` reads, but includes more context:

```python
def _render_delta_for_llm(self, delta_items):
    """Render delta items into text for the LLM compactor prompt."""
    parts = []
    for item in delta_items:
        role = item.get("role", "")
        content = item.get("content", "")
        kind = item.get("kind", "")
        tool_name = item.get("tool_name", "")

        if role == "user":
            parts.append(f"[User]: {content[:2000]}")
        elif role == "assistant":
            parts.append(f"[Assistant]: {content[:2000]}")
        elif role == "tool":
            label = tool_name or kind or "tool"
            # Truncate large tool outputs to keep prompt reasonable
            truncated = content[:3000]
            if len(content) > 3000:
                truncated += f"\n... ({len(content)} chars total, truncated)"
            parts.append(f"[Tool:{label}]: {truncated}")
        elif kind == "compact_summary":
            parts.append(f"[Prior Summary]: {content[:2000]}")

    return "\n\n".join(parts)
```

Note: Total delta text should be capped (e.g., 20,000 chars) to avoid the compact call itself being too expensive. If delta_text exceeds the cap, trim from the oldest items first.

### 2.5 Include `compact_call_usage` in return value

The `compact()` method currently returns a dict. Add the new field:

```python
result = {
    "summary_called": True,
    "summary_mode": summary_mode,  # NEW: "deterministic" | "llm" | "deterministic_fallback"
    "compact_call_usage": compact_call_usage,  # NEW: None for deterministic, dict for llm
    # ... existing fields ...
}
```

### 2.6 Emit compact usage in event

When emitting the `"compaction_created"` event, include `compact_call_usage` in the event payload so downstream consumers can observe it.

---

## Step 3: Modify `pico/core/context_orchestrator.py` — Tier3 Trigger

### 3.1 Current trigger logic

Currently triggers compaction ONLY when `metadata.get("prompt_over_budget")` is true. This is a character-budget signal (60k chars), not a pressure-tier signal.

### 3.2 New trigger logic

Add a second trigger path: if pressure tier is `tier3_summary` AND there are enough delta events to justify a compact call.

```python
def build(self, snapshot):
    prompt, metadata = self.agent.context_manager.build(snapshot.request)

    # Existing: prompt_over_budget → compact (deterministic)
    # New: tier3_summary → compact (llm mode)

    context_usage = metadata.get("context_usage", {})
    pressure_tier = context_usage.get("pressure_tier", "tier0_observe")

    should_compact = False
    summary_mode = "deterministic"
    compact_trigger = None

    if metadata.get("prompt_over_budget"):
        # Existing path: hard budget overflow → deterministic compact
        compact_trigger = "auto_prompt_over_budget"
        summary_mode = "deterministic"
    elif pressure_tier == "tier3_summary":
        # New path: high pressure → LLM handoff compact
        # Only if there's sufficient history to justify a compact call
        history = snapshot.session.get("history", [])
        last_boundary = (snapshot.session.get("context_summary") or {}).get("last_included_event_id")
        delta_count = self._count_delta_events(history, last_boundary)
        if delta_count >= 4:  # At least 4 events since last compact
            compact_trigger = "auto_tier3_summary"
            summary_mode = "llm"

    if compact_trigger and len(snapshot.session.get("history", [])) > 4:
        plan = self.agent.compact_manager.plan(trigger=compact_trigger)
        summary = self.agent.compact_history(
            trigger=plan.trigger,
            keep_recent_turns=plan.keep_recent_turns,
            summary_mode=summary_mode,
        )
        should_compact = bool(summary.get("summary_called", True))
        if should_compact:
            prompt, metadata = self.agent.context_manager.build(snapshot.request)
        metadata.update({
            "auto_compacted": should_compact,
            "auto_compaction_plan": plan.to_dict(),
            "auto_compaction_summary": summary,
        })
    elif compact_trigger and len(snapshot.session.get("history", [])) <= 4:
        metadata["auto_compacted"] = False
        metadata["auto_compaction_skip_reason"] = "history_too_short_for_auto_compaction"

    # ... rest of metadata attachment ...
```

### 3.3 New helper: `_count_delta_events(history, last_boundary_event_id) -> int`

```python
def _count_delta_events(self, history, last_boundary_event_id):
    """Count events after the last compaction boundary."""
    if not last_boundary_event_id:
        return len(history)
    for i, item in enumerate(history):
        if item.get("event_id") == last_boundary_event_id:
            return len(history) - i - 1
    return len(history)
```

---

## Step 4: Modify `pico/core/context_budget_summary.py` — Track Compact Cost

### 4.1 Add field to schema

Add `compact_call_usage` to the budget summary dict:

```python
context_budget_summary = {
    # ... existing fields ...
    "compact_call_usage": None | {
        "input_tokens": int,
        "output_tokens": int,
        "total_tokens": int,
        "cached_tokens": int,
        "model": str,
        "provider": str,
    },
    "compact_net_benefit_tokens": None | int,  # main_request_savings - compact_call_total_tokens
}
```

### 4.2 Compute net benefit

When building the budget summary, if `compact_call_usage` is present:

```python
if compact_call_usage:
    main_savings = prior_estimated_tokens - current_estimated_tokens
    compact_cost = compact_call_usage["total_tokens"]
    net_benefit = main_savings - compact_cost
    summary["compact_net_benefit_tokens"] = net_benefit
```

---

## Step 5: Modify `pico/core/context_report.py` — Surface Compact Usage

Add `compact_call_usage` from the orchestrator's metadata into the report dict under a new key:

```python
report["compact_call_usage"] = metadata.get("auto_compaction_summary", {}).get("compact_call_usage")
```

---

## Step 6: Wire through `runtime.py` — Pass `summary_mode`

The `agent.compact_history()` method in `runtime.py` currently delegates to `CompactManager.compact()`. Update its signature to accept and pass through `summary_mode`:

```python
def compact_history(self, trigger="manual", keep_recent_turns=2, summary_mode="deterministic"):
    return self.compact_manager.compact(
        trigger=trigger,
        keep_recent_turns=keep_recent_turns,
        summary_mode=summary_mode,
    )
```

---

## Step 7: Tests

### 7.1 `tests/test_context_handoff.py`

Unit tests for the new module:

| Test | What it verifies |
|------|-----------------|
| `test_parser_valid_output` | Parser correctly extracts all sections from well-formed LLM output |
| `test_parser_missing_optional_sections` | Parser handles missing Constraints/Blockers gracefully |
| `test_parser_missing_goal` | Parser returns empty goal → signals fallback needed |
| `test_parser_garbage_input` | Parser returns HandoffSummary with empty goal on unparseable input |
| `test_render_roundtrip` | `render_handoff_summary(parse(text))` preserves critical info |
| `test_adapter_success` | Mock model client returns valid output → HandoffSummary returned |
| `test_adapter_model_failure` | Mock model client raises → returns None, last_usage is None |
| `test_adapter_parse_failure` | Mock model returns garbage → returns None, last_usage still recorded |
| `test_adapter_usage_tracking` | After successful call, `last_usage` has correct token counts |
| `test_delta_text_truncation` | Large delta items are truncated to prevent oversized prompt |

### 7.2 `tests/test_llm_compaction_integration.py`

Integration tests for the full flow:

| Test | What it verifies |
|------|-----------------|
| `test_tier3_triggers_llm_compact` | When pressure_tier == "tier3_summary" and delta >= 4, LLM compact is triggered |
| `test_tier3_insufficient_delta_no_compact` | tier3 with < 4 delta events does NOT trigger |
| `test_llm_fallback_to_deterministic` | If LLM call fails, deterministic compact runs and session is consistent |
| `test_prompt_over_budget_still_deterministic` | Existing `prompt_over_budget` path unchanged (deterministic) |
| `test_old_session_no_drift` | Session with only `context_summary` metadata (no `compact_call_usage`) works fine |
| `test_replacement_ledger_preserved` | LLM compact does not corrupt or reset the replacement ledger |
| `test_low_pressure_no_compact` | tier0/tier1/tier2 do NOT trigger any compaction |
| `test_compact_usage_in_budget_summary` | `compact_call_usage` appears in budget summary after LLM compact |
| `test_net_benefit_calculation` | Net benefit = main_request_savings - compact_call_cost is computed correctly |
| `test_summary_mode_in_compact_result` | `summary_mode` field in compact result is "llm", "deterministic", or "deterministic_fallback" |

### 7.3 Update existing tests

In `tests/test_compact.py` and `tests/test_context_orchestrator.py`:
- Ensure existing tests still pass with default `summary_mode="deterministic"`.
- Add a guard test that `compact()` with `summary_mode="deterministic"` produces identical behavior to current.

---

## Implementation Order

Execute in this order to maintain green tests at each step:

1. **Create `pico/core/context_handoff.py`** with HandoffSummary, HandoffParser, HandoffAdapter, render_handoff_summary, HANDOFF_PROMPT_TEMPLATE.
2. **Write `tests/test_context_handoff.py`** — all unit tests for the new module. Run and verify green.
3. **Modify `pico/core/compact.py`** — add `summary_mode` param, `_render_delta_for_llm()`, LLM path with fallback. Default remains deterministic.
4. **Modify `pico/core/runtime.py`** — pass `summary_mode` through `compact_history()`.
5. **Modify `pico/core/context_orchestrator.py`** — add tier3_summary trigger with `_count_delta_events()`.
6. **Modify `pico/core/context_budget_summary.py`** — add `compact_call_usage` and `compact_net_benefit_tokens`.
7. **Modify `pico/core/context_report.py`** — surface compact usage.
8. **Write `tests/test_llm_compaction_integration.py`** — integration tests. Run full suite.
9. **Run existing test suite** (`pytest tests/`) — verify no regressions.

---

## Constraints & Guardrails

1. **Never call model client directly.** Always use `complete_model()` from `pico/providers/base.py`.
2. **Delta text cap.** Cap `_render_delta_for_llm()` output at 20,000 chars total to prevent the compact call from being more expensive than the savings.
3. **Fallback is mandatory.** Any exception or parse failure in the LLM path MUST result in deterministic compaction running. The session must never be left in an inconsistent state.
4. **No session schema changes.** The `context_summary` session field keeps its existing shape. The `compact_call_usage` is transient metadata in the build result, not persisted in the session (unless we decide otherwise in Phase 2).
5. **`summary_mode` default is "deterministic".** All existing code paths and tests should be unaffected unless explicitly opting into "llm" mode.
6. **Minimum delta threshold.** Do not trigger LLM compact if fewer than 4 events exist in the delta. The LLM call cost is only justified when there's meaningful history to compress.
7. **max_summary_tokens = 1024.** Keep the compact call's output budget small.
8. **Item truncation in delta rendering.** Each item capped at 2000-3000 chars. Tool outputs especially can be enormous.

---

## What This Does NOT Do (Phase 2+)

- No `/compact --llm` CLI command
- No new final_readiness reasons
- No retention decision taxonomy changes
- No live provider benchmarks
- No encrypted compact blobs
- No UI for inspecting handoff summaries

---

## Acceptance Criteria

Phase 1 is done when:

1. `tier3_summary` pressure → LLM handoff summary is generated automatically
2. LLM failure → seamless fallback to deterministic, no user-visible error
3. `compact_call_usage` tracked separately in budget summary with net benefit calculation
4. All existing tests pass unchanged (deterministic paths untouched)
5. New test suite covers: parser, adapter, fallback, trigger logic, ledger preservation, old session compat
