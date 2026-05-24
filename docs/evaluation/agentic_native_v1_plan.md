# Agentic-Native v1 Plan

Agentic-native v1 expands from 3 to 8 tasks. The goal is to evaluate native
agent harness behavior separately from delegated v3 human-gate scenarios.

## Tasks

| Task | Category | Intent | Status |
|---|---|---|---|
| `agentic_native_plan_001` | plan_mode | Plan artifact creation and evidence | carried from v0 |
| `agentic_native_skill_001` | skill | Project skill invocation and session events | carried from v0 |
| `agentic_native_memory_001` | memory | Memory write with native evidence | fixed in v0 and carried to v1 |
| `agentic_native_checkpoint_artifact_001` | resume | Checkpoint artifact smoke, not true two-pass resume | smoke-level |
| `agentic_native_readonly_exploration_001` | tool_policy | Read-only exploration report smoke, not true subagent coverage | smoke-level |
| `agentic_native_approval_001` | tool_policy | Approval boundary record | drafted |
| `agentic_native_sandbox_001` | sandbox | Path escape refusal | drafted |
| `agentic_native_long_output_001` | evidence | Long output artifact reference | drafted |

## Evidence Mode

Native agentic tasks use:

```text
evidence_mode = native
```

They must keep report, trace, task state, session, and session event evidence in
the copied bundle. Functional pass with evidence failure is not a release pass.

Delegated v3 human-gate scenarios use:

```text
evidence_mode = delegated_human_gate
evidence_consistency = not_applicable
```

Delegated human-gate runs should not be mixed into the native evidence
consistency denominator.

`agentic_native_checkpoint_artifact_001` is a checkpoint artifact smoke, not a
release-grade resume benchmark. Release-grade resume coverage requires a
two-pass runner flow with `--resume latest`, session continuity, task-state
continuity, checkpoint id checks, changed paths, and evidence consistency.

`agentic_native_readonly_exploration_001` is a read-only exploration report
smoke, not a true subagent benchmark. The previous
`agentic_native_subagent_001` proxy is quarantined until native evidence can
verify `subagent_started`, `subagent_completed`, `subagent_mode=explore`, and
read-only scope.

## Promotion Criteria

- v1 schema loads.
- no-key report-card tests cover delegated evidence `not_applicable`.
- at least one DeepSeek live smoke is recorded.
- Failures are classified as model behavior, task design, or runner/runtime.
- Functional pass plus evidence fail is fixed before release, not ignored.

## Live Smoke Result

Run: `/tmp/picobench-v03-agentic-native`

| Task | Strict | Failure Category | Decision |
|---|---:|---|---|
| `agentic_native_plan_001` | 1 | none | keep |
| `agentic_native_skill_001` | 1 | none | keep |
| `agentic_native_memory_001` | 1 | none | keep; evidence blocker fixed |
| `agentic_native_checkpoint_artifact_001` | 1 | none | downgraded from failed resume proxy to checkpoint artifact smoke |
| `agentic_native_readonly_exploration_001` | 1 | none | downgraded from failed subagent proxy to read-only exploration smoke |
| `agentic_native_approval_001` | 1 | none | keep as smoke-level approval boundary task |
| `agentic_native_sandbox_001` | 1 | none | keep as smoke-level sandbox refusal task |
| `agentic_native_long_output_001` | 1 | none | keep as smoke-level evidence task |

Final verification after downgrade: 8 tasks, 8 strict pass, 0 strict failure,
evidence consistency `1.0`, output directory
`/tmp/picobench-v03-final-agentic-native-7218d68`.
