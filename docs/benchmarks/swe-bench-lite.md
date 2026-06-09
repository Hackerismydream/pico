# SWE-bench Lite

`pico-swebench` generates SWE-bench prediction files with a shell-only agent
inside the task Docker image. A non-empty `model_patch` is required for a valid
prediction. An official resolved rate requires running the SWE-bench harness.

## Install

```bash
uv sync --extra swebench
```

This installs both `datasets` for prediction generation and the official
`swebench` harness for local evaluation.

Environment:

```bash
export PICO_DEEPSEEK_API_KEY=...
export PICO_DEEPSEEK_MODEL=deepseek-v4-pro
```

For local benchmark worktrees, copying the ignored project `.env` is also valid:

```bash
cp /path/to/pico/.env /path/to/pico-v3-swebench-lite-deepseek/.env
chmod 600 /path/to/pico-v3-swebench-lite-deepseek/.env
```

Do not commit `.env`; it is intentionally ignored.

If this checkout uses a private Pico config file, pass it explicitly:

```bash
--config /absolute/path/to/private-config.toml
```

## Smoke

```bash
uv run pico-swebench \
  --subset lite \
  --split test \
  --slice 0:1 \
  --workers 1 \
  --provider deepseek \
  --max-steps 80 \
  --max-new-tokens 4096 \
  --output outputs/pico-v3-swebench-lite-smoke
```

Outputs:

```text
outputs/pico-v3-swebench-lite-smoke/preds.json
outputs/pico-v3-swebench-lite-smoke/summary.json
outputs/pico-v3-swebench-lite-smoke/<instance_id>/<instance_id>.traj.json
```

Docker unavailable expected behavior:

```text
exit code 1
summary.json exists
setup_error_count > 0
non_empty_predictions == 0
preds.json contains no fake non-empty patch
```

## Official Evaluation

Run official evaluation only after `preds.json` contains one or more non-empty
patches:

```bash
export DOCKER_HOST=unix:///Users/martinlos/.colima/pico/docker.sock

uv run --extra swebench python -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench_Lite \
  --split test \
  --predictions_path outputs/pico-v3-swebench-lite-smoke/preds.json \
  --max_workers 1 \
  --run_id pico-v3-lite-smoke \
  --report_dir artifacts/benchmark/pico-v3-lite-smoke-eval
```

`preds.json` may be either JSONL or the dictionary format written by
`pico-swebench`; the official harness accepts both.

When using Colima, set `DOCKER_HOST` to the active context endpoint from
`docker context inspect`. The official harness uses the Python Docker SDK, so
the Docker CLI context alone is not always enough.

Small batch:

```bash
uv run pico-swebench \
  --subset lite \
  --split test \
  --slice 0:10 \
  --workers 2 \
  --provider deepseek \
  --max-steps 80 \
  --max-new-tokens 4096 \
  --output outputs/pico-v3-swebench-lite-10
```

Full Lite:

```bash
export HF_DATASETS_OFFLINE=1
export HF_HUB_OFFLINE=1

uv run pico-swebench \
  --subset lite \
  --split test \
  --workers 4 \
  --provider deepseek \
  --max-steps 80 \
  --max-new-tokens 4096 \
  --output outputs/pico-v3-swebench-lite
```

Long runs can be resumed from `preds.json`. By default, existing non-empty
patches are skipped and existing empty patches are retried. To preserve already
attempted empty predictions as part of the benchmark denominator and continue
with only unseen instances, add:

```bash
--include-empty-predictions --skip-existing-empty-predictions
```

## Summary

```bash
uv run --extra swebench python scripts/summarize-swebench.py outputs/pico-v3-swebench-lite-smoke \
  --output artifacts/benchmark/swebench-lite-smoke-summary.json
```

If an official evaluation report directory is available:

```bash
uv run --extra swebench python scripts/summarize-swebench.py outputs/pico-v3-swebench-lite-smoke \
  --eval-report-dir /path/to/evaluation/run \
  --output artifacts/benchmark/swebench-lite-smoke-summary.json
```
