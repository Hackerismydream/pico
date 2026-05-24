# Agentic-Native Evidence Review

Source runs:

- original smoke: `/tmp/picobench-live-smoke-agentic-native`
- v0 evidence fix rerun: `/tmp/picobench-agentic-native-rerun2`

- commit: `f7cdecc28060d2bef46240f380966976c2a99b09`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- strict_pass_rate: `1.0`
- evidence_consistency_rate: `0.6666666666666666`

## Finding

The original lower evidence consistency rate was caused by
`agentic_native_memory_001`. Earlier smoke evidence showed a verifier gap; the
2026-05-23 full native run then exposed the stricter blocker: the slash-only
memory scenario could write memory but still miss `report_path`, `trace_path`,
and `task_state_path` in the copied evidence bundle.

The fix is task design, not hidden-test relaxation: the memory scenario now
forces a model turn after `/remember`, gives the runner enough steps to finish,
and includes the native `evidence` verifier.

## Task Review

| Task | Strict | Evidence consistency check | Review |
|---|---:|---:|---|
| `agentic_native_plan_001` | 1 | 1 | Report, trace, and task state matched |
| `agentic_native_skill_001` | 1 | 1 | Report, trace, and task state matched |
| `agentic_native_memory_001` | 1 | 1 | Fixed by replacing slash-only prompt with remember plus confirmation turn |

## Decision

Fixed in `benchmarks/picobench-agentic-native-v0.yaml` and carried into
`benchmarks/picobench-agentic-native-v1.yaml`.

Rerun result:

- command: `uv run python scripts/run_picobench.py --suite agentic-native --benchmark benchmarks/picobench-agentic-native-v0.yaml --output-dir /tmp/picobench-agentic-native-rerun2 --provider deepseek --approval auto --sandbox best_effort --json`
- tasks: 3
- strict_passed: 3
- strict_failed: 0
- strict_pass_rate: `1.0`
- evidence_consistency_rate: `1.0`

The previous 2026-05-23 memory failure is closed for v0. Native v1 still needs
its own live smoke because it adds five drafted native scenarios.
