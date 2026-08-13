# Tracing Runtime overhead

> **Status: implemented campaign, no formal result recorded here.** Generated
> evidence remains outside Git and owns every measured metric.

This PicoBench track measures the local Runtime tax of Pico's in-tree Tracing.
It does not test an external Provider or claim production latency.

## Treatment and workload

The campaign runs 20 balanced blocks of 50 paired Turns, for 1,000 pairs and
2,000 total Turns. Every Turn crosses the shared Runtime Assembly and Agent
Loop, makes two deterministic local Provider calls, executes `trace_lookup`
once, and returns `TRACE_OK`. The sole treatment axis is `PICO_TRACING=0` versus
`PICO_TRACING=1`.

Each enabled Turn must retain exactly one terminal `session.turn` trace joined
to two `llm.call` spans and one `tool.call` span. The disabled arm must emit no
trace bytes. Both arms must complete the same workload with identical replies
and call counts.

## Metrics and evidence

The aggregate reports P50 and P95 latency for both arms, the relative overhead,
a block-clustered bootstrap 95% interval for the P95 ratio, and bytes per traced
Turn. Measurement validity requires all correctness, correlation, Pair-count,
arm-balance, and disabled-no-output Gates to pass. There is no preregistered
"good overhead" threshold; the result is an estimated operational cost, not an
optimization claim.

The immutable manifest binds the Pico commit, Python and platform identity,
workload, Pair count, and bootstrap settings. Per-block receipts retain raw
Turn latency and terminal outcomes plus SHA-256 receipts for every trace file.
The offline verifier rebuilds `raw-outcomes.jsonl`, `aggregate.json`,
`claim-eligibility.json`, `verifier-report.json`, and `inventory.json`.

## Operator commands

```bash
make picobench-tracing-plan
make picobench-tracing-run
make picobench-tracing-verify
```

Set `PICO_TRACING_OUTPUT` to use a new evidence root. After the repository moves
past the measured candidate, set `PICO_TRACING_COMMIT` to the full commit bound
by the retained manifest before running the offline verifier.
