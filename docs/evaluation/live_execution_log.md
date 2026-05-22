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
