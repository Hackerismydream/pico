---
id: picobench-004
scope: evaluation
status: completed
depends-on:
  - picobench-002
authority-issue: 59
gates: [G3, G4, G5]
requires-live-provider: false
---

# PicoBench Context Task Pack

## Objective

Measure whether Pico's Curator phase-B history manager preserves verified
long-task constraints with less Context cost than a FIFO-tail manager.

## Context

The comparison changes the declared phase-B `history_manager` axis. The
Curator arm includes its selected history, Working State, archive bookkeeping,
fallbacks, and `after_turn` hook; the FIFO arm does not. Identity, Bootstrap,
user Memory, active Skills, retrieved Skills, Tool definitions, model, budget,
Session, and Verifier stay identical. This task does not restore a public
multi-engine Context configuration or claim that history selection alone
caused the result.

Owned paths:

```text
benchmarks/picobench/packs/context/
benchmarks/picobench/tasks/context/
tests/test_picobench_context_track.py
tests/integration/test_picobench_context_e2e.py
```

## Path

1. Freeze eight tasks with 30 to 80 prior messages, early required
   constraints, superseded decisions, long Tool Results, irrelevant noise, and
   deterministic final artifacts.
2. Implement checkout-only FIFO-tail and full-history phase-B managers against
   the existing `SegmentBuilder` seam; use FIFO versus Curator for the formal
   Pair.
3. Save the actual variant diff and reject any change outside
   `history_manager`.
4. Aggregate main-Agent input and full Trial usage, including Curator calls.
5. Verify artifact contents, required historical constraints, forbidden path
   mutations, and final task success outside the Agent workspace.
6. Report per-task token deltas, verifier passes, Context path, latency, net
   regressions, and exploratory task-clustered intervals.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_context_track.py -q
uv run pytest tests/integration/test_picobench_context_e2e.py -q
```

Acceptance:

- all eight tasks have positive and corruption tests for their Verifier;
- Pair drift outside `history_manager` is zero;
- token accounting includes auxiliary Context calls;
- positive token claims require at least six tasks with at least two
  success-matched, usage-complete Pairs each;
- positive eligibility uses the contract's equal-task macro formula and
  requires at least 15 percent Trial-total input reduction, treatment pass
  count not below control, at least six tasks with lower token use, and no task
  losing two of three passes;
- the eight-task result is reported as exploratory, not a precise
  non-inferiority result.
