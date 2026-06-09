#!/usr/bin/env bash
set -o pipefail

cd /Users/martinlos/code/pico-v3-swebench-lite-deepseek || exit 2

RUN_ID=swebench-lite-deepseek-full-20260609-141010
OUT=outputs/$RUN_ID
ART=artifacts/benchmark/$RUN_ID

HF_DATASETS_OFFLINE=1 HF_HUB_OFFLINE=1 \
DOCKER_HOST=unix:///Users/martinlos/.colima/pico/docker.sock uv run --extra swebench pico-swebench \
  --subset lite \
  --split test \
  --workers 8 \
  --provider deepseek \
  --max-steps 10 \
  --max-new-tokens 4096 \
  --openai-timeout 60 \
  --command-timeout 600 \
  --include-empty-predictions \
  --skip-existing-empty-predictions \
  --output "$OUT" 2>&1 | tee "$ART/logs/pico-swebench.log"
status=${PIPESTATUS[0]}
printf "%s\n" "$status" > "$ART/pico-swebench-exit-code.txt"

uv run --extra swebench python scripts/summarize-swebench.py "$OUT" \
  --output "$ART/swebench-lite-deepseek-prediction-summary.json" \
  > "$ART/logs/summarize-swebench.log" 2>&1
printf "%s\n" "$?" > "$ART/summarize-swebench-exit-code.txt"

exit "$status"
