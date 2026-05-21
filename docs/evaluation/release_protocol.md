# PicoBench Release Protocol

## Required Evidence

Each release run must produce:

- `summary.json`
- `summary.md`
- `task_results.jsonl`
- `logs/<task>.stdout.txt`
- `logs/<task>.stderr.txt`
- `evidence/<task>-runN/report.json`
- `evidence/<task>-runN/trace.jsonl`
- `evidence/<task>-runN/task_state.json`
- `evidence/<task>-runN/session.json`
- `evidence/<task>-runN/events.jsonl`
- `evidence/<task>-runN/evidence_bundle_manifest.json`

## Commands

L0 runtime regression:

```bash
uv run python scripts/run_picobench_runtime.py \
  --benchmark benchmarks/picobench-runtime-v1.json \
  --output-dir /tmp/picobench-runtime-smoke \
  --json
```

Core smoke:

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_001 \
  --output-dir /tmp/picobench-pr-smoke \
  --json
```

Agentic smoke:

```bash
uv run python scripts/run_picobench.py \
  --suite agentic \
  --benchmark benchmarks/picobench-agentic-v1.yaml \
  --output-dir /tmp/picobench-agentic-smoke
```

Ablation protocol placeholder:

```bash
uv run python scripts/run_picobench_ablation.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --output-dir /tmp/picobench-ablation-plan \
  --plan-only
```

Live provider smoke, when local provider credentials are configured:

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_001 \
  --output-dir /tmp/picobench-core-live-smoke \
  --approval auto \
  --sandbox best_effort \
  --json
```

Full unit regression:

```bash
uv run pytest tests/ -q
```

## Reporting Rule

Only `strict_pass_rate` is externally comparable. Functional-only pass rates are diagnostic because public tests can miss unsafe or weak patches. Skipped TUI tasks are reported in `skipped` and are not counted as strict passes.
