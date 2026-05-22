# PicoBench Live Execution Log

Append one section per live run. Do not fabricate missing values.

## Run <date>-<provider>-<suite>

- commit:
- branch:
- provider:
- model:
- suite:
- tasks:
- command:
- output_dir:
- status:
- strict_pass_rate:
- failures:
- notes:

### Artifacts

- summary:
- evidence bundle:
- failure reports:

### Failure analysis

| Task | Failure | Category | Suspected cause | Action |
|---|---|---|---|---|

## Current HEAD deterministic verification 2026-05-22

- commit: `068318fea6d5aee29353656464c598667f678466`
- branch: `codex/picobench-v3`
- provider: none
- model: none
- suite: no-key gates
- tasks: deterministic/static gates only
- command: `uv run pytest tests/ -q`; `uv run python scripts/check_picobench_tasks.py --benchmark benchmarks/picobench-core-v1.yaml --min-tasks 30 --json-output /tmp/picobench-current-quality.json`; `uv run python scripts/check_picobench_tasks.py --benchmark benchmarks/picobench-core-v1.yaml --task core_011 --task core_026 --min-tasks 2 --run-public-tests --run-hidden-tests --require-initial-failing --json-output /tmp/picobench-current-quality-exec.json`; `uv run python scripts/run_picobench_runtime.py --benchmark benchmarks/picobench-runtime-v1.json --output-dir /tmp/picobench-current-runtime --json`
- output_dir: `/tmp/picobench-current-runtime`
- status: completed
- strict_pass_rate: not applicable
- failures: none
- notes: local current-HEAD no-key verification passed: `267 passed, 2 skipped, 6 warnings`; task quality 30 tasks passed; executable quality subset 2 tasks passed; L0 runtime passed `2/2`.

### Artifacts

- summary: `/tmp/picobench-current-quality.json`, `/tmp/picobench-current-quality-exec.json`
- evidence bundle: `/tmp/picobench-current-runtime/runtime_artifact.json`
- failure reports: none

### Failure analysis

| Task | Failure | Category | Suspected cause | Action |
|---|---|---|---|---|
| deterministic gates | none | none | none | Current HEAD no-key gate is reproducible locally |

## GitHub Actions status 2026-05-22

- commit: `068318fea6d5aee29353656464c598667f678466`
- branch: `codex/picobench-v3`
- workflow: `PicoBench`
- run id: `26271849474`
- status: completed
- conclusion: success
- notes: GitHub run logs show schema/validator tests `27 passed`, task quality `30` tasks passed, executable task-quality subset `2` tasks passed, L0 runtime `2/2`, and artifact `picobench-deterministic-artifacts` uploaded as artifact id `7154009507`.

The live smoke workflow file exists on `codex/picobench-v3`, but GitHub Actions
does not list or dispatch it from this branch because it is not on the default
branch. The `picobench-live` environment was not returned by the environments
API, so it still needs to be created before protected manual live runs can be
triggered from GitHub.

## Run 2026-05-22-deepseek-core10

- commit: `068318fea6d5aee29353656464c598667f678466`
- branch: `codex/picobench-v3`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `core`
- tasks: `core_001`, `core_003`, `core_011`, `core_017`, `core_021`, `core_026`, `core_027`, `core_028`, `core_029`, `core_030`
- command: `uv run python scripts/run_picobench.py --suite core --benchmark benchmarks/picobench-core-v1.yaml --task core_001 --task core_003 --task core_011 --task core_017 --task core_021 --task core_026 --task core_027 --task core_028 --task core_029 --task core_030 --output-dir /tmp/picobench-phase3b-core10 --provider deepseek --approval auto --sandbox best_effort --json`
- output_dir: `/tmp/picobench-phase3b-core10`
- status: completed with strict failures
- strict_pass_rate: `0.8`
- failures: `core_027`, `core_028`
- notes: Phase 3B 10-task core subset. Evidence consistency rate was `1.0`; failures are hidden-edge task failures, not runner/evidence failures.

### Artifacts

- summary: `/tmp/picobench-phase3b-core10/summary.json`
- evidence bundle: `/tmp/picobench-phase3b-core10/evidence/`
- failure reports: `/tmp/picobench-phase3b-core10/failures/`
- manifest: `/tmp/picobench-phase3b-core10/run_manifest.json`
- provider config: `/tmp/picobench-phase3b-core10/provider_config_redacted.json`

### Failure analysis

| Task | Failure | Category | Suspected cause | Action |
|---|---|---|---|---|
| `core_027` | Hidden tests failed for no-frontmatter summary fallback and empty tag filtering | `hidden_test_failure` | Model handled public frontmatter path but missed hidden renderer/parser edges | Keep as benchmark signal; do not fix task unless hidden test is wrong |
| `core_028` | Hidden test failed because blank-token audit was over-redacted | `hidden_test_failure` | Model fixed public redaction but applied `[REDACTED]` even when no token exists | Keep as benchmark signal; repeated failure confirms useful hidden edge |

## Run 2026-05-22-deepseek-core001

- commit: `f7cdecc28060d2bef46240f380966976c2a99b09`
- branch: `codex/picobench-v3`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `core`
- tasks: `core_001`
- command: `uv run python scripts/run_picobench.py --suite core --benchmark benchmarks/picobench-core-v1.yaml --task core_001 --output-dir /tmp/picobench-live-smoke-core001 --provider deepseek --approval auto --sandbox best_effort --json`
- output_dir: `/tmp/picobench-live-smoke-core001`
- status: completed
- strict_pass_rate: `1.0`
- failures: none
- notes: minimal Phase 3 live smoke; provider config saved only as redacted host/model/has-key metadata.

### Artifacts

- summary: `/tmp/picobench-live-smoke-core001/summary.json`
- evidence bundle: `/tmp/picobench-live-smoke-core001/evidence/core_001-run1`
- failure reports: none
- manifest: `/tmp/picobench-live-smoke-core001/run_manifest.json`
- provider config: `/tmp/picobench-live-smoke-core001/provider_config_redacted.json`

### Failure analysis

| Task | Failure | Category | Suspected cause | Action |
|---|---|---|---|---|
| `core_001` | none | none | none | Use as live provider connectivity smoke evidence |

## Run 2026-05-22-deepseek-core-multifile

- commit: `f7cdecc28060d2bef46240f380966976c2a99b09`
- branch: `codex/picobench-v3`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `core`
- tasks: `core_026`, `core_027`, `core_028`, `core_029`, `core_030`
- command: `uv run python scripts/run_picobench.py --suite core --benchmark benchmarks/picobench-core-v1.yaml --task core_026 --task core_027 --task core_028 --task core_029 --task core_030 --output-dir /tmp/picobench-live-smoke-multifile --provider deepseek --approval auto --sandbox best_effort --json`
- output_dir: `/tmp/picobench-live-smoke-multifile`
- status: completed with strict failures
- strict_pass_rate: `0.4`
- failures: `core_027`, `core_028`, `core_030`
- notes: this is real benchmark signal from a harder multi-file smoke, not a CI failure and not a fabricated green run.

### Artifacts

- summary: `/tmp/picobench-live-smoke-multifile/summary.json`
- evidence bundle: `/tmp/picobench-live-smoke-multifile/evidence/`
- failure reports: `/tmp/picobench-live-smoke-multifile/failures/`
- manifest: `/tmp/picobench-live-smoke-multifile/run_manifest.json`
- provider config: `/tmp/picobench-live-smoke-multifile/provider_config_redacted.json`

### Failure analysis

| Task | Failure | Category | Suspected cause | Action |
|---|---|---|---|---|
| `core_027` | Hidden tests failed for document without frontmatter and empty tag filtering | `hidden_test_failure` | Model fixed public frontmatter path but missed hidden edge cases | Keep as benchmark signal; no runner fix needed |
| `core_028` | Hidden tests failed for maintainer read permission and blank-token audit behavior | `hidden_test_failure` | Model satisfied public maintainer write/redaction path but over-redacted blank token and missed read inheritance | Keep as benchmark signal; review prompt only if repeated models misread role policy |
| `core_030` | Functional tests passed, but `must_read_before_write` failed | `tool_policy_violation` | Model wrote after reading tests/graph but did not read the target write file before modifying it | Keep strict failure; process validator is working as intended |

## Run 2026-05-22-deepseek-agentic-native

- commit: `f7cdecc28060d2bef46240f380966976c2a99b09`
- branch: `codex/picobench-v3`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `agentic-native`
- tasks: `agentic_native_plan_001`, `agentic_native_skill_001`, `agentic_native_memory_001`
- command: `uv run python scripts/run_picobench.py --suite agentic-native --benchmark benchmarks/picobench-agentic-native-v0.yaml --output-dir /tmp/picobench-live-smoke-agentic-native --provider deepseek --approval auto --sandbox best_effort --json`
- output_dir: `/tmp/picobench-live-smoke-agentic-native`
- status: completed
- strict_pass_rate: `1.0`
- failures: none
- notes: native plan, skill, and memory examples all strictly passed; evidence consistency rate was `0.6666666666666666`, so evidence consistency should be reviewed before using this as more than smoke evidence.

### Artifacts

- summary: `/tmp/picobench-live-smoke-agentic-native/summary.json`
- evidence bundle: `/tmp/picobench-live-smoke-agentic-native/evidence/`
- failure reports: none
- manifest: `/tmp/picobench-live-smoke-agentic-native/run_manifest.json`
- provider config: `/tmp/picobench-live-smoke-agentic-native/provider_config_redacted.json`

### Failure analysis

| Task | Failure | Category | Suspected cause | Action |
|---|---|---|---|---|
| `agentic_native_plan_001` | none | none | none | Keep in smoke set |
| `agentic_native_skill_001` | none | none | none | Keep in smoke set |
| `agentic_native_memory_001` | none | none | none | Review evidence-consistency metric before release runs |
