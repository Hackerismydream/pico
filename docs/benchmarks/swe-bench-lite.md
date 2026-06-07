# SWE-bench Lite

`pico-swebench` generates SWE-bench prediction files with a shell-only agent
inside the task Docker image. A non-empty `model_patch` is required for a valid
prediction. An official resolved rate requires running the SWE-bench harness.

## Install

```bash
uv sync --extra swebench
```

Environment:

```bash
export PICO_DEEPSEEK_API_KEY=...
export PICO_DEEPSEEK_MODEL=deepseek-v4-pro
```

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
python -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench_Lite \
  --split test \
  --predictions_path outputs/pico-v3-swebench-lite-smoke/preds.json \
  --max_workers 1 \
  --run_id pico-v3-lite-smoke
```

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
uv run pico-swebench \
  --subset lite \
  --split test \
  --workers 4 \
  --provider deepseek \
  --max-steps 80 \
  --max-new-tokens 4096 \
  --output outputs/pico-v3-swebench-lite
```

## Summary

```bash
python scripts/summarize-swebench.py outputs/pico-v3-swebench-lite-smoke \
  --output artifacts/benchmark/swebench-lite-smoke-summary.json
```

If an official evaluation report directory is available:

```bash
python scripts/summarize-swebench.py outputs/pico-v3-swebench-lite-smoke \
  --eval-report-dir /path/to/evaluation/run \
  --output artifacts/benchmark/swebench-lite-smoke-summary.json
```
