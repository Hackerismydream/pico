# SWE-bench Lite

`pico-swebench` generates SWE-bench prediction files with a shell-only agent
inside the task Docker image. The default profile uses a hard mini-SWE-agent
style submission contract: the agent must create `patch.txt`, inspect it, and
submit with `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt`.
A natural-language final answer is not a valid SWE-bench submission. A
non-empty `model_patch` is required for a valid prediction. An official resolved
rate requires running the SWE-bench harness.

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
  --submission-contract sentinel \
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

No-submission expected behavior:

```text
exit_status_counts.missing_submission_sentinel > 0
non_empty_predictions does not increase
trajectory records the final git diff audit for debugging only
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
  --submission-contract sentinel \
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
  --submission-contract sentinel \
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

## Contract A/B

Use the previous full-run official report to select a stratified 20-task smoke
slice:

```bash
uv run python scripts/select-swebench-ab-slice.py \
  --eval-report artifacts/benchmark/swebench-lite-deepseek-full-20260609-141010/official-eval/pico-v3__deepseek-v4-pro.pico-v3-lite-deepseek-full-20260609-141010.json \
  --output artifacts/benchmark/swebench-lite-ab-slice20.json
```

The selector writes:

```text
10 old empty-patch task ids
5 old resolved task ids
5 old non-empty unresolved task ids
filter_regex for pico-swebench --filter
```

Run the legacy baseline with the old final-diff behavior:

```bash
filter="$(uv run python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path('artifacts/benchmark/swebench-lite-ab-slice20.json').read_text())['filter_regex'])
PY
)"

uv run pico-swebench \
  --subset lite \
  --split test \
  --filter "$filter" \
  --workers 4 \
  --provider deepseek \
  --submission-contract legacy-final-diff \
  --experiment-label slice20-legacy-final-diff \
  --include-empty-predictions \
  --output outputs/swebench-lite-slice20-legacy
```

Run the hard sentinel contract:

```bash
uv run pico-swebench \
  --subset lite \
  --split test \
  --filter "$filter" \
  --workers 4 \
  --provider deepseek \
  --submission-contract sentinel \
  --experiment-label slice20-sentinel \
  --include-empty-predictions \
  --output outputs/swebench-lite-slice20-sentinel
```

Gate before a full 300-task rerun:

```text
non_empty_predictions >= 2x legacy baseline on the 20-task slice
old resolved group loses at most 1 resolved task after official eval
average steps or wall time <= 2x baseline
patch_pollution_count / attempted_instances < 10%
if non-empty coverage rises but resolved does not, tune prompt/contract before full 300
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
