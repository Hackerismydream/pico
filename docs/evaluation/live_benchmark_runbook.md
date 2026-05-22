# PicoBench Live Benchmark Runbook

This runbook describes the manual path for controlled live benchmark runs. It
assumes the default no-key CI gates remain separate from live provider runs.

## 1. Prepare Provider Env

Set provider credentials in the shell or in the local `.env`. Do not pass keys
as CLI arguments and do not commit `.env`.

For DeepSeek:

```bash
export DEEPSEEK_API_KEY=...
export DEEPSEEK_MODEL=deepseek-v4-pro
export DEEPSEEK_API_BASE=https://api.deepseek.com/anthropic
```

## 2. Choose Task Subset

Start small:

- `core_001` for a minimal core smoke;
- `core_026`-`core_030` for multi-file core tasks;
- all tasks in `picobench-agentic-native-v0.yaml` for native plan, skill, and
  memory behaviors.

Do not start Phase 3 with a full 30-task run.

## 3. Run No-Key Gates

```bash
uv run pytest tests/ -q

uv run python scripts/check_picobench_tasks.py \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --min-tasks 30 \
  --json-output /tmp/picobench-task-quality.json

uv run python scripts/run_picobench_runtime.py \
  --benchmark benchmarks/picobench-runtime-v1.json \
  --output-dir /tmp/picobench-runtime \
  --json
```

## 4. Run Live Core Smoke

Minimal core smoke:

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_001 \
  --output-dir /tmp/picobench-live-smoke-core001 \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

Phase 3B 10-task core subset:

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_001 \
  --task core_003 \
  --task core_011 \
  --task core_017 \
  --task core_021 \
  --task core_026 \
  --task core_027 \
  --task core_028 \
  --task core_029 \
  --task core_030 \
  --output-dir /tmp/picobench-phase3b-core10 \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

Small mixed core smoke:

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_001 \
  --task core_011 \
  --task core_026 \
  --output-dir /tmp/picobench-live-core-smoke \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

Multi-file core smoke:

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_026 \
  --task core_027 \
  --task core_028 \
  --task core_029 \
  --task core_030 \
  --output-dir /tmp/picobench-live-smoke-multifile \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

## 5. Run Agentic-Native Smoke

```bash
uv run python scripts/run_picobench.py \
  --suite agentic-native \
  --benchmark benchmarks/picobench-agentic-native-v0.yaml \
  --output-dir /tmp/picobench-live-smoke-agentic-native \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

## 6. Write Manifests

After each live run:

```bash
uv run python scripts/write_picobench_run_manifest.py \
  --output-dir /tmp/picobench-live-core-smoke \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort
```

Repeat for each output directory.

## 7. Inspect Summary

Read:

- `summary.json`;
- `summary_compact.json`;
- `summary.md`;
- `task_results.jsonl`;
- `failures/*.md` when strict failures exist.

Use `strict_pass_rate` as the run result. Functional-only pass rates are
diagnostic.

## 8. Save Evidence

Keep the output directory intact until the run is reviewed. A live run is not
auditable without its logs, copied evidence, summaries, and manifest files.

## 9. Classify Failures

Use `docs/evaluation/failure_analysis_guide.md` to decide whether each failure
is a provider issue, model issue, task issue, runner issue, evidence issue, or
Pico product/runtime bug.

## 10. Update Execution Log

Append the run to `docs/evaluation/live_execution_log.md` and update
`docs/evaluation/live_results_summary.md`. Do not invent missing values; write
`not executed` when a provider run did not happen.
