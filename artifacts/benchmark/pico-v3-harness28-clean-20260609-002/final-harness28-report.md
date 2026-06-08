# Pico v3 Harness-Bench 28-task Clean Run Report

## Run metadata
- Status: COMPLETED_LOCAL_OPEN_SOURCE_28_TASK_RUN
- Run ID: pico-v3-harness28-clean-20260609-002
- Pico branch: codex/v3-benchmark-integrations-clean
- Harness-Bench checkout: /Users/martinlos/code/harness-bench
- Harness-Bench commit: 8d31d6c initial commit
- Harness-Bench task count loaded: 28
- Model/provider: deepseek / deepseek-v4-pro
- Mode: live
- Runner command: `uv run python -m clawbench_v2.cli run-suite --model pico-v3-local --mode live --delete-sandbox`
- Wall elapsed: 3261.681s

## What was fixed before this run
- Pico benchmark wrapper now exports variables loaded from `PICO_BENCH_ENV`, so child `uv run pico` receives provider keys.
- Pico provider config now resolves legacy process env vars such as `PICO_DEEPSEEK_API_KEY`, not only project `.env` legacy values.
- Harness-Bench task `09-git-pr-merge` now removes runner-created empty `workspace/in` and `workspace/out` placeholders before cloning into `workspace`.
- Harness-Bench task `23-supply-chain-alert` now has the missing local fixture files required by its oracle:
  - `fixtures/data/consumer_trends.csv`
  - `fixtures/data/warehouse_stock.json`
- The Harness-Bench summarizer now reads `oracle_result.score` when a task uses `score` instead of `outcome_score`, and it avoids treating an invalid Harness-Bench `scoring.combined_score=1.0` fallback as the real task score.

## Code verification
- ruff: pass (`uv run ruff check pico tests scripts`)
- pytest: pass (`uv run pytest tests/test_pico.py tests/test_benchmark_integrations.py -q`; 91 passed)

## Result summary
- run-suite exit code: 0
- tasks loaded: 28
- tasks seen in run log: 28
- result JSON files copied into artifact: 28
- runner / fixture / oracle exceptions: 0
- oracle_passed_tasks: 10
- oracle_failed_tasks: 18
- oracle_pass_rate: 0.35714285714285715
- average_outcome_score: 0.5570642857142857
- average_combined_score: 0.5570642857142857
- average_process_score: null
- average_total_tokens: null

## Passed tasks
- 01-file
- 02-exec
- 03-browser
- 04-meeting-summary
- 05-email-triage
- 06-access-bilibili
- 07-session-memory
- 08-image-recognize
- 09-git-pr-merge
- 14-image-edit

## Non-passing tasks
- 10-office-docs
- 12-code-debug
- 13-doc-synthesis
- 15-task-decomposition
- 16-heartbeat-test
- 17-like-record
- 18-album-metadata-retrieval
- 18-provider-failover-audit
- 19-incident-runbook-synthesis
- 19-landmark-recognition
- 20-football-shot-map-analysis
- 20-heartbeat-escalation
- 21-US-bank-failures-history
- 22-log-troubleshooting
- 23-supply-chain-alert
- 24-security-injection-defense
- 25-code-repair-pytest
- 26-db-doc-consistency

## Interpretation
This is a completed local run of the current open-source Harness-Bench checkout available on this machine. It is not the 106-task public leaderboard benchmark shown on harness-bench.ai.

The previous local blockers were removed: the run now produces 28/28 result JSON files and has no runner-level exceptions. The result should be described as a local 28-task Harness-Bench run, not as an official leaderboard submission.

The correct headline number for this run is:

> Pico v3 completed the current open-source 28-task Harness-Bench suite locally with 10/28 oracle-perfect tasks, 35.71% oracle pass rate, and 55.71% average outcome/combined score.

## Artifact map
- Final report: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/final-harness28-report.md`
- Summary JSON: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/harness-bench-full-summary.json`
- Run log: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/logs/harness-run-suite.log`
- Task list: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/logs/harness-tasks.json`
- Result JSONs: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/results/pico-v3-local/`
- Config snapshots: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/config-snapshots/`
- External Harness-Bench local patch: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/harness-bench-local-patches.diff`
- Code verification: `artifacts/benchmark/pico-v3-harness28-clean-20260609-002/code-verification.txt`

## Remaining limitation
The official website leaderboard uses 106 tasks. This local checkout exposes 28 tasks, so this report cannot establish an official leaderboard rank. To run the 106-task benchmark, the missing official task package, fixtures, and scoring configuration are required.
