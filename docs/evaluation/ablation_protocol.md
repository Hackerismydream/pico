# PicoBench Ablation Protocol

## Variants

Required first-line variants:

- `pico-full`
- `pico-no-memory`
- `pico-no-plan`
- `pico-no-subagent`
- `pico-no-skills`

`pico-no-sandbox` is diagnostic only and must not be presented as a recommended configuration.

## Metrics

Each variant should eventually report:

- `solve@1_strict`
- `solve@3_strict`
- `functional_pass_rate`
- `safety_violation_rate`
- `evidence_consistency_rate`
- `avg_tool_steps`
- `avg_cost_usd`
- `avg_wall_time_ms`
- `failure_category_counts`

## Current Implementation

`scripts/run_picobench_ablation.py` writes a machine-readable planned summary with `planned_only: true`. The branch does not add new runtime feature flags just to force ablations. When feature flags exist, this script can wrap `scripts/run_picobench.py` per variant and fill the metrics from each run's `summary.json`.

## Interpretation

An ablation only matters if it changes strict pass, safety, evidence quality, cost, or latency. A feature that increases token usage without improving strict pass or safety should be treated as a product question, not assumed beneficial.
