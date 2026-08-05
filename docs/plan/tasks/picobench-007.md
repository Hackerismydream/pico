---
id: picobench-007
scope: evaluation
status: completed
depends-on:
  - picobench-001
authority-issue: 59
gates: [G3, G5, G6]
requires-live-provider: false
---

# PicoBench reducer and reports

## Objective

Rebuild Pair validity, retrieval metrics, task-level effects, failure
breakdowns, and positive Claim Gates entirely from the immutable manifest and
stored evidence records.

## Context

The independent statistical unit is the task, not a repeated model run.
Context, Memory, Skill, and Tool Packs also have different controls, so their
effects cannot be relabeled as one Pico-full overall improvement. This task
implements a generic reducer over declarative `ClaimRule` records; Pack metric
names and thresholds are data, not hard-coded dependencies.

Owned paths:

```text
benchmarks/picobench/reducer.py
benchmarks/picobench/statistics.py
benchmarks/picobench/claims.py
benchmarks/picobench/report.py
tests/test_picobench_reporting.py
```

## Path

1. Load the immutable manifest to recover the planned denominators,
   `ClaimRule` records, retry limits, and identity digests; reject missing or
   incompatible evidence records.
2. Select only Comparison Blocks whose every arm resolves to `passed`,
   `task_failed`, or `task_timeout`; preserve Provider and infrastructure
   contamination.
3. Select the earliest block-attempt number with every arm measurable. Never
   mix attempts. A product failure cannot trigger a rerun, although it may run
   again when another arm contaminates the same Block.
4. Calculate first-attempt end-to-end pass, product pass, run-level pass,
   task-level pass, and paired task delta.
5. Rebuild all Retrieval Case metrics from selected query-block attempts and
   preserve their separate 260-Case denominator.
6. Average repetition deltas within each task, then perform 10,000 bootstrap
   samples over task ids using a plan-derived recorded random seed.
7. Require each single-axis comparison to have at least 22 of 24 valid Pairs
   and every task to have at least two of three valid Pairs.
8. Emit `ship_complete`, `measurement_valid`, and
   `positive_claim_eligible` separately; positive eligibility implies the
   first two.
9. Label cross-Pack aggregation as a stratified pack-specific-control summary.
10. Rebuild `summary.json`, `cv-metrics.json`, and the local report without
   Runtime, Provider, Memory, or MCP calls.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_reporting.py -q
```

Acceptance:

- corrupted, asymmetric, drifted, or under-covered Pairs cannot produce a
  positive claim;
- all attempts, failures, timeouts, cancellations, and inconclusive records
  remain visible;
- final-campaign inconclusive count must be zero;
- repeated rebuilds preserve semantic content and digest;
- every metric traces to Pack, task, variant, repetition, attempt, and
  Verifier;
- every retrieval metric traces to suite, query, configuration, query-block
  attempt, label, and anonymous ranked output;
- an eight-task interval is labeled exploratory;
- a complete valid negative experiment produces
  `positive_claim_eligible=false`, not a failed Ship.
