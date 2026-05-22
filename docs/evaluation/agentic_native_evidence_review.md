# Agentic-Native Evidence Review

Source run: `/tmp/picobench-live-smoke-agentic-native`

- commit: `f7cdecc28060d2bef46240f380966976c2a99b09`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- strict_pass_rate: `1.0`
- evidence_consistency_rate: `0.6666666666666666`

## Finding

The lower evidence consistency rate was caused by
`agentic_native_memory_001`. The task strictly passed, but it did not include
the `evidence` verifier, so its checks did not include
`report_trace_session_consistency`. The report card treats missing evidence
consistency checks as false for that metric.

This was not a trace/report contradiction. It was a benchmark task verifier
gap.

## Task Review

| Task | Strict | Evidence consistency check | Review |
|---|---:|---:|---|
| `agentic_native_plan_001` | 1 | 1 | Report, trace, and task state matched |
| `agentic_native_skill_001` | 1 | 1 | Report, trace, and task state matched |
| `agentic_native_memory_001` | 1 | 0 | Missing `evidence` verifier, not a failed consistency check |

## Decision

Fix the task, not the runner or runtime. `agentic_native_memory_001` should
include the `evidence` verifier like the plan and skill tasks.

The previous agentic-native smoke remains useful as functional smoke evidence,
but it should not be treated as release-grade agentic evidence until rerun with
the memory task evidence verifier present.
