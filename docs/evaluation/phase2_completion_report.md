# PicoBench Phase 2 Completion Report

Date: 2026-05-22

Branch: `codex/picobench-v3`

## Scope

This report covers the Phase 2 items called out by the GPT Pro review. Phase 2
builds on the existing v0.1 harness instead of replacing Phase 1.

## Delivered Items

| Item | Status | Evidence |
|---|---|---|
| Task quality checker | Done | `pico/evaluation/task_quality.py`, `scripts/check_picobench_tasks.py`, `tests/test_task_quality.py` |
| Core task count | Done | `benchmarks/picobench-core-v1.yaml` now has 25 tasks, each with visible and hidden fixtures |
| Process validators | Done | `required_tool_sequence`, `must_run_tests`, `must_read_before_write`, `required_trace_event`, `required_session_event`, `artifact_exists` |
| Native agentic examples | Done | `benchmarks/picobench-agentic-native-v0.yaml` has plan, skill, and memory tasks |
| Live/dogfood skeleton | Done | `benchmarks/picobench-live/`, `docs/evaluation/live_dogfood_protocol.md` |
| Ablation status | Done | `docs/evaluation/ablation_status.md`; runner remains explicit `planned_only` |
| Report card enhancements | Done | category breakdown, timeout count, duration p50/p95, failure taxonomy table, `summary_compact.json` |

## Verification

Fresh local verification on 2026-05-22:

```bash
uv run pytest tests/test_benchmark_schema.py tests/test_task_quality.py tests/test_process_validators.py tests/test_report_card.py -q
```

Result:

```text
15 passed in 0.11s
```

```bash
uv run pytest tests/ -q
```

Result:

```text
259 passed, 2 skipped, 6 warnings in 68.32s
```

```bash
uv run python scripts/check_picobench_tasks.py \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --min-tasks 25 \
  --json-output /tmp/picobench-phase2-quality/task_quality.json
```

Result:

```json
{"passed": true, "task_count": 25, "hidden_fixture_count": 25, "issues": []}
```

```bash
uv run python scripts/run_picobench_runtime.py \
  --benchmark benchmarks/picobench-runtime-v1.json \
  --output-dir /tmp/picobench-phase2-runtime \
  --json
```

Result:

```json
{"passed": 2, "failed": 0, "pass_rate": 1.0}
```

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_001 \
  --task core_011 \
  --output-dir /tmp/picobench-phase2-core-subset \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

Result:

```json
{"task_count": 2, "strict_passed": 2, "strict_failed": 0, "strict_pass_rate": 1.0, "provider": "deepseek"}
```

```bash
uv run python scripts/run_picobench.py \
  --suite agentic-native \
  --benchmark benchmarks/picobench-agentic-native-v0.yaml \
  --task agentic_native_memory_001 \
  --output-dir /tmp/picobench-phase2-agentic-native \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

Result:

```json
{"task_count": 1, "strict_passed": 1, "strict_failed": 0, "strict_pass_rate": 1.0, "provider": "deepseek"}
```

```bash
uv run python scripts/run_picobench_ablation.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --output-dir /tmp/picobench-phase2-ablation \
  --plan-only
```

Result:

```json
{"status": "planned", "variant_count": 5}
```

## Not Claimed

This branch does not claim a public live leaderboard run. The live/dogfood
protocol and manifest skeleton are present, but private held-out tasks and
hidden tests are intentionally not committed to this repository.

The ablation runner still records planned variants only. Real ablation numbers
require product-level feature flags for disabling memory, plan mode, subagents,
and skills through the same public CLI boundary.
