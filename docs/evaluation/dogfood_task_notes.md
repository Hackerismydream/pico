# PicoBench Dogfood Task Notes

The v0.3 provenance audit found no task that can honestly remain
`pico-dogfood-derived` without a source commit or reference patch. Tasks that
were inspired by Pico mechanisms but hand-authored for benchmark coverage were
reclassified as `pico-inspired-synthetic`.

| Task | Source | Source Commit / Patch | Original Problem | Public Behavior | Hidden Edge | Contamination Risk | Decision |
|---|---|---|---|---|---|---|---|
| none | `pico-dogfood-derived` | n/a | No release-grade dogfood-derived task has auditable provenance in v0.3 | n/a | n/a | n/a | Do not claim dogfood-derived coverage until real source commits or reference patches are recorded |

## Reclassified Pico-Inspired Tasks

| Task | Source | Rationale | Decision |
|---|---|---|---|
| `core_031` | `pico-inspired-synthetic` | Config/default/CLI precedence resembles Pico work but has no source commit | keep as synthetic benchmark signal |
| `core_032` | `pico-inspired-synthetic` | Report/manifest status resembles Pico reporting work but has no source commit | keep as synthetic benchmark signal |
| `core_036` | `pico-inspired-synthetic` | Checkpoint/resume state preservation resembles Pico runtime work but has no source commit | keep as synthetic benchmark signal |
| `core_037` | `pico-inspired-synthetic` | Trace/report consistency resembles Pico evidence work but has no source commit | keep as synthetic benchmark signal |
| `core_039` | `pico-inspired-synthetic` | Provider fallback resembles Pico provider config work but has no source commit | keep as synthetic benchmark signal |
| `core_040` | `pico-inspired-synthetic` | Evidence bundle copying resembles Pico runner work but has no source commit | keep as synthetic benchmark signal |
| `agentic_native_checkpoint_artifact_001` | `pico-inspired-synthetic` | Checkpoint artifact smoke resembles resume work but is not a real source-derived task | keep as smoke only |
| `agentic_native_readonly_exploration_001` | `pico-inspired-synthetic` | Read-only exploration resembles subagent workflow but is not true subagent coverage | keep as smoke only |
| `agentic_native_approval_001` | `pico-inspired-synthetic` | Approval boundary report resembles tool-policy work but has no source commit | keep as smoke only |
| `agentic_native_sandbox_001` | `pico-inspired-synthetic` | Sandbox refusal resembles path-policy work but has no source commit | keep as smoke only |
