# Pico v3 Full Benchmark Report

## Run metadata
- Status: BLOCKED_BY_INFRA
- Branch: codex/v3-benchmark-integrations-clean
- Commit: 49243be
- Base branch: v3
- RUN_ID: pico-v3-full-20260608-135159
- Date: 2026-06-08T15:59:10
- DOCKER_HOST: unix:///Users/martinlos/.colima/pico/docker.sock
- Docker context: colima-pico
- Model/provider: deepseek / deepseek-v4-pro
- Harness workers: sequential run-suite
- SWE-bench prediction workers: 4

## Code verification
- ruff: pass (`uv run ruff check pico tests scripts`)
- pytest: pass (`244 passed, 2 skipped, 6 warnings`)

## Harness-Bench full suite
- run-suite exit code: 0
- run-suite tasks seen in log: 28
- result JSON files summarized: 26
- oracle_passed_tasks: 8
- oracle_failed_tasks: 18
- oracle_pass_rate: 0.3076923076923077
- average_outcome_score: 0.47842105263157897
- average_process_score: None
- average_combined_score: 0.6188461538461538
- average_total_tokens: None
- failed_task_ids: ['06-access-bilibili', '10-office-docs', '12-code-debug', '13-doc-synthesis', '15-task-decomposition', '16-heartbeat-test', '17-like-record', '18-album-metadata-retrieval', '18-provider-failover-audit', '19-incident-runbook-synthesis', '19-landmark-recognition', '20-football-shot-map-analysis', '20-heartbeat-escalation', '21-US-bank-failures-history', '22-log-troubleshooting', '24-security-injection-defense', '25-code-repair-pytest', '26-db-doc-consistency']
- task-level runner/fixture errors not included in result JSON summary: ['09-git-pr-merge', '23-supply-chain-alert']
- Harness-Bench working tree dirty: yes
- summary artifact: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/harness-bench-full-summary.json
- log artifact: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/logs/harness-run-suite.log

## SWE-bench Lite full prediction attempt
- prediction exit code: 0
- selected_instances: 300
- attempted_instances: 300
- skipped_instances: 0
- non_empty_predictions: 0
- total_predictions_in_file: 0
- empty_patch_count: 300
- setup_error_count: 296
- model_error_count: 4
- timeout_count: 0
- prediction output: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/outputs/pico-v3-swebench-lite-full-pico-v3-full-20260608-135159
- predictions file: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/outputs/pico-v3-swebench-lite-full-pico-v3-full-20260608-135159/preds.json
- run summary artifact: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/swebench-lite-full-run-summary.json
- prediction summary artifact: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/swebench-lite-full-prediction-summary.json
- prediction log artifact: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/logs/swebench-predictions-full.log

### SWE-bench failure buckets
```json
{
  "docker_image_pull_failed": 231,
  "docker_tls_handshake_timeout": 65,
  "provider_incomplete_read": 2,
  "provider_request_failed": 2
}
```

## SWE-bench Lite official evaluation
- official_evaluation_exit_code: not_run
- submitted_instances: null
- completed_instances: null
- resolved_instances: null
- resolved_rate: null
- official eval report dir: null
- official summary artifact: null
- status artifact: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/swebench-official-eval-status.txt

Official evaluation was not run because `non_empty_predictions == 0`. Per the benchmark plan, an official SWE-bench evaluation is only valid after prediction generation produces at least one non-empty patch.

## Interpretation
This is not a full successful SWE-bench Lite benchmark result. Pico attempted the full selected SWE-bench Lite test set (`selected_instances=300`, `attempted_instances=300`), but produced zero non-empty predictions because most instances failed during Docker image setup. The dominant failure class is Docker Hub / CloudFront SWE-bench image pull failure, so the final status is `BLOCKED_BY_INFRA` rather than a model resolved-rate score.

Harness-Bench did complete its full run-suite command. Its summary shows the current full-suite pass/score under this local checkout, while also noting two task-level runner/fixture failures that did not produce normal result JSON files.

## Artifacts
- artifact dir: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159
- run id: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/run_id.txt
- code verification: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/code-verification.txt
- Harness tasks: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/logs/harness-tasks.json
- Harness run log: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/logs/harness-run-suite.log
- Harness summary: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/harness-bench-full-summary.json
- SWE prediction output: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/outputs/pico-v3-swebench-lite-full-pico-v3-full-20260608-135159
- SWE prediction summary: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/swebench-lite-full-prediction-summary.json
- SWE run summary: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/swebench-lite-full-run-summary.json
- SWE official eval status: /Users/martinlos/code/pico-v3-benchmark-integrations-clean/artifacts/benchmark/pico-v3-full-20260608-135159/swebench-official-eval-status.txt
