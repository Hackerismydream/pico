# Harness-Bench

Harness-Bench exercises Pico through its `generic_cli` adapter. The adapter runs
`scripts/bench-pico-v3.sh`, which invokes the current checkout with a prompt
file, fixed session id, non-interactive approval, and DeepSeek by default.

## Install

```bash
git clone https://github.com/Qihoo360/harness-bench /path/to/harness-bench
cd /path/to/harness-bench
python3 -m pip install -e .
```

If system Python rejects global installs, use a virtual environment in the
Harness-Bench checkout.

## Config

`local/app.pico.yaml`:

```yaml
data_dir: data/pico-v3
tasks_dir: tasks
default_timeout_sec: 900
default_rounds: 1
results_dir: data/pico-v3/results
work_root: data/pico-v3/sandbox
```

`local/models.pico.yaml`:

```yaml
models:
  pico-v3-local:
    adapter: generic_cli
    command: /absolute/path/to/pico/scripts/bench-pico-v3.sh
    session_prefix: clawbenchv2-pico-v3
    timeout_sec: 900
    args:
      - "--workspace"
      - "{workspace}"
      - "--prompt-file"
      - "{prompt_file}"
      - "--session-id"
      - "{session_id}"
      - "--task-id"
      - "{task_id}"
      - "--model-id"
      - "{model_id}"
      - "--max-steps"
      - "16"
```

Environment:

```bash
export CLAWBENCHV2_APP_CONFIG=/path/to/harness-bench/local/app.pico.yaml
export CLAWBENCHV2_MODELS_CONFIG=/path/to/harness-bench/local/models.pico.yaml
export PICO_DEEPSEEK_API_KEY=...

# Optional private local setup:
export PICO_BENCH_ENV=/absolute/path/to/private.env
export PICO_BENCH_CONFIG=/absolute/path/to/pico-config.toml
export PICO_BENCH_MODEL=deepseek-v4-pro
```

`PICO_BENCH_ENV` may export local variables such as:

```bash
export PICO_DEEPSEEK_API_KEY="..."
export PICO_DEEPSEEK_MODEL="deepseek-v4-pro"
```

Do not commit private env or config files.

## Smoke

```bash
PYTHONPATH=src python3 -m clawbench_v2.cli run-task \
  --task 01-file \
  --model pico-v3-local \
  --mode live

PYTHONPATH=src python3 -m clawbench_v2.cli run-task \
  --task 07-session-memory \
  --model pico-v3-local \
  --mode live
```

Expected evidence for a passed run:

- command exits `0`
- `oracle_result.outcome_score == 1.0`
- Pico writes `.pico/runs/<run_id>/trace.jsonl` and `report.json` under the task workspace

## Summary

```bash
python /absolute/path/to/pico/scripts/summarize-harness-bench.py \
  /path/to/harness-bench/data/pico-v3/results/pico-v3-local \
  --output /absolute/path/to/pico/artifacts/benchmark/harness-bench-pico-core-summary.json
```

The summary reports attempted tasks, oracle pass rate, average scores, token
usage when available, failed task ids, and per-task rows.
