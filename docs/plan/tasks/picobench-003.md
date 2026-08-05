---
id: picobench-003
scope: evaluation
status: completed
depends-on:
  - picobench-002
authority-issue: 59
gates: [G2]
requires-live-provider: false
---

# PicoBench Runtime tracks

## Objective

Measure Scheduler request semantics separately from full deterministic Runtime
composition so neither result overclaims the other.

## Context

R0 proves Lane, pool, cancellation, and shutdown invariants with a scripted
`TurnRunner`. R1 proves that the benchmark host actually reaches Agent Loop,
Tool, Session, and Delivery through the real composition. An INJECT request may
merge, fall back, or cancel, so request count cannot be equated with runner
invocation count.

Owned paths:

```text
benchmarks/picobench/packs/runtime/
tests/test_picobench_runtime_track.py
tests/integration/test_picobench_runtime_track_e2e.py
```

## Path

1. Give every R0 request a unique `message_id` and every runner invocation a
   unique execution id.
2. Record exactly one accepted-request fate:
   `executed`, `merged_into_running_turn`, `fallback_executed`,
   `cancelled_before_start`, or `cancelled_while_running`.
3. Execute 2,000 accepted requests over 64 conversations, 16 USER slots, four
   system slots, and mixed APPEND, INJECT, INTERRUPT, and cancellation; then
   submit 64 explicit post-drain rejection probes that must not receive a
   handle.
4. Measure no-contention `dispatch_overhead_ms`, contended `queue_wait_ms`, and
   `execution_latency_ms` separately.
5. Use Runtime Assembly for composition, then submit exactly 100 R1 requests
   through Scheduler, `AgentTurnRunner`, Agent Loop, deterministic Provider,
   deterministic Tool, Session, and DeliveryHub. Require 92 readable
   Session/Delivery outcomes for the scenarios that reach those boundaries.
6. Include clean completion, expected Tool failure, Provider failure,
   cancellation, and delivery outcomes in R1.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_runtime_track.py -q
uv run pytest tests/integration/test_picobench_runtime_track_e2e.py -q
```

Acceptance:

- all 2,000 accepted R0 requests reach exactly one accepted-request fate, and
  all 64 rejected submissions are separately accounted without a handle;
- lost request, unresolved handle, unexpected duplicate request execution,
  lifecycle contradiction, and pool-limit violation are zero;
- every R1 request enters through `Scheduler.submit` and uses
  `AgentTurnRunner`;
- model, Tool, Session, terminal, and delivery evidence share the expected
  Turn identity;
- the RecordingOutlet covers delivered, injected failure, and no-outlet
  outcomes after DeliveryHub idle;
- `TurnEnded.latency_ms` is not reported as scheduling overhead;
- the result is labeled deterministic Runtime evidence, not real LLM load.
- R1 is labeled benchmark-host full-path evidence, not proof that every product
  Host adapter was exercised.
