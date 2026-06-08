#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

workspace=""
prompt_file=""
session_id=""
max_steps="${PICO_BENCH_MAX_STEPS:-16}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      workspace="$2"
      shift 2
      ;;
    --prompt-file)
      prompt_file="$2"
      shift 2
      ;;
    --session-id)
      session_id="$2"
      shift 2
      ;;
    --task-id|--model-id)
      shift 2
      ;;
    --max-steps)
      max_steps="$2"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$workspace" || -z "$prompt_file" || -z "$session_id" ]]; then
  echo "missing --workspace, --prompt-file, or --session-id" >&2
  exit 2
fi

if [[ -n "${PICO_BENCH_ENV:-}" ]]; then
  if [[ ! -f "$PICO_BENCH_ENV" ]]; then
    echo "PICO_BENCH_ENV does not exist: $PICO_BENCH_ENV" >&2
    exit 2
  fi
  # shellcheck source=/dev/null
  set -a
  source "$PICO_BENCH_ENV"
  set +a
fi

provider="${PICO_BENCH_PROVIDER:-deepseek}"
cmd=(
  uv run pico
  --cwd "$workspace"
  --repo-root "$workspace"
  --prompt-file "$prompt_file"
  --session-id "$session_id"
  --provider "$provider"
  --approval auto
  --non-interactive
  --max-steps "$max_steps"
)

if [[ -n "${PICO_BENCH_MODEL:-}" ]]; then
  cmd+=(--model "$PICO_BENCH_MODEL")
fi

if [[ -n "${PICO_BENCH_CONFIG:-}" ]]; then
  cmd+=(--config "$PICO_BENCH_CONFIG")
fi

cd "$repo_root"
exec "${cmd[@]}"
