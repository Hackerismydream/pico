# PicoBench Phase 2 Completion Report

Date: 2026-05-22

Branch: `codex/picobench-v3`

Status: internal PicoBench v0.2 candidate. This is not a public benchmark or
leaderboard.

## Scope

This report covers the Phase 2 items called out by the GPT Pro review. Phase 2
builds on the existing v0.1 harness instead of replacing Phase 1.

## Delivered Items

| Item | Status | Evidence |
|---|---|---|
| Task quality checker | Done | `pico/evaluation/task_quality.py`, `scripts/check_picobench_tasks.py`, `tests/test_task_quality.py` |
| Core task count | Done | `benchmarks/picobench-core-v1.yaml` now has 30 tasks, each with visible and hidden fixtures |
| Process validators | Done | `required_tool_sequence`, `must_run_tests`, `must_read_before_write`, `required_trace_event`, `required_session_event`, `artifact_exists` |
| Native agentic examples | Done | `benchmarks/picobench-agentic-native-v0.yaml` has plan, skill, and memory tasks |
| Live/dogfood skeleton | Done | `benchmarks/picobench-live/`, `docs/evaluation/live_dogfood_protocol.md` |
| Ablation status | Done | `docs/evaluation/ablation_status.md`; runner remains explicit `planned_only` |
| Report card enhancements | Done | category breakdown, timeout count, duration p50/p95, failure taxonomy table, `summary_compact.json` |

## Verification

Fresh local verification on 2026-05-22:

```bash
uv run pytest tests/test_benchmark_schema.py tests/test_task_quality.py tests/test_process_validators.py tests/test_evaluation_validators.py tests/test_report_card.py -q
```

Result:

```text
27 passed in 1.82s
```

```bash
uv run pytest tests/ -q
```

Result:

```text
266 passed, 2 skipped, 6 warnings in 67.07s
```

```bash
uv run python scripts/check_picobench_tasks.py \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --min-tasks 30 \
  --json-output /tmp/picobench-hardening-quality/task_quality.json
```

Result:

```json
{"passed": true, "task_count": 30, "hidden_fixture_count": 30, "issues": []}
```

```bash
uv run python scripts/run_picobench_runtime.py \
  --benchmark benchmarks/picobench-runtime-v1.json \
  --output-dir /tmp/picobench-hardening-runtime \
  --json
```

Result:

```json
{"passed": 2, "failed": 0, "pass_rate": 1.0, "total_tasks": 2}
```

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_001 \
  --task core_011 \
  --output-dir /tmp/picobench-hardening-core-subset \
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
  --output-dir /tmp/picobench-hardening-agentic-memory \
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
  --output-dir /tmp/picobench-hardening-ablation \
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

## Phase 3 Transition

Phase 2 hardening is complete enough to move from benchmark framework
construction into controlled live benchmark operation. Phase 3 keeps default CI
as a no-key deterministic gate and moves live provider calls into manual smoke
runs with redacted manifests and evidence bundles. Current Phase 3 status lives
in:

- `docs/evaluation/phase3_plan.md`
- `docs/evaluation/ci_strategy.md`
- `docs/evaluation/live_benchmark_runbook.md`
- `docs/evaluation/live_execution_log.md`
- `docs/evaluation/live_results_summary.md`

## Hardening Addendum

Fresh local hardening verification on 2026-05-22:

The task-quality CLI now creates the parent directory for `--json-output`,
because the first hardening rerun exposed that nested output paths were not
reproducible.

```bash
uv run python scripts/check_picobench_tasks.py \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_011 \
  --task core_026 \
  --min-tasks 2 \
  --run-public-tests \
  --run-hidden-tests \
  --require-initial-failing \
  --json-output /tmp/picobench-hardening-quality-exec.json
```

Result:

```json
{"passed": true, "task_count": 2, "hidden_fixture_count": 2, "issues": []}
```

```bash
uv run python scripts/check_picobench_tasks.py \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_026 \
  --task core_027 \
  --task core_028 \
  --task core_029 \
  --task core_030 \
  --min-tasks 5 \
  --run-public-tests \
  --run-hidden-tests \
  --require-initial-failing \
  --json-output /tmp/picobench-hardening-quality-new-core.json
```

Result:

```json
{"passed": true, "task_count": 5, "hidden_fixture_count": 5, "issues": []}
```

```bash
uv run python scripts/run_picobench.py \
  --suite agentic-native \
  --benchmark benchmarks/picobench-agentic-native-v0.yaml \
  --task agentic_native_skill_001 \
  --output-dir /tmp/picobench-hardening-agentic-skill \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

Result:

```json
{"task_count": 1, "strict_passed": 1, "strict_failed": 0, "strict_pass_rate": 1.0, "provider": "deepseek"}
```

Hardening changes:

- `agentic_native_skill_001` now uses a fixture-provided project skill and real
  REPL slash input `/release staging`.
- Task quality checks can optionally run public tests, inject hidden tests, and
  detect initial all-green tasks.
- `ArtifactExistsVerifier` can validate artifact paths referenced from trace
  events and artifact manifests.
- Git changed-path collection expands untracked directories to files, which
  keeps report/task-state evidence comparable to the actual workspace diff.
- CI now runs schema/task-quality/process-validator/report-card tests,
  executable task-quality subset checks, the static task quality gate, and L0
  runtime regression without live-provider calls.
