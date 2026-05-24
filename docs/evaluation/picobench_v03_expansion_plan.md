# PicoBench v0.3 Expansion Plan

## Goal

Move from 45 live/agent tasks to 60 live/agent tasks without turning the suite
into a pile of synthetic microtasks.

## Current

| Suite | Count |
|---|---:|
| Core coding tasks | 30 |
| v3 human-gate delegated scenarios | 12 |
| Agentic-native tasks | 3 |
| Live/agent total | 45 |

## Target

| Suite | Current | Target | Delta |
|---|---:|---:|---:|
| Core coding tasks | 30 | 40 | +10 |
| Agentic-native tasks | 3 | 8 | +5 |
| v3 human-gate delegated scenarios | 12 | 12 | 0 |
| Live/agent total | 45 | 60 | +15 |

## New Tasks

| Task | Source | Category | Multi-file | Hidden tests | Status |
|---|---|---|---:|---:|---|
| `core_031` | Pico-inspired synthetic | configuration | 1 | 1 | implemented |
| `core_032` | Pico-inspired synthetic | feature/evidence | 1 | 1 | implemented |
| `core_033` | synthetic | security_fix | 0 | 1 | implemented |
| `core_034` | synthetic | test_repair | 0 | 1 | implemented |
| `core_035` | synthetic | refactor | 1 | 1 | implemented |
| `core_036` | Pico-inspired synthetic | resume | 1 | 1 | implemented |
| `core_037` | Pico-inspired synthetic | evidence | 1 | 1 | implemented |
| `core_038` | synthetic | sandbox | 1 | 1 | implemented |
| `core_039` | Pico-inspired synthetic | provider | 1 | 1 | implemented |
| `core_040` | Pico-inspired synthetic | evidence | 1 | 1 | implemented |
| `agentic_native_checkpoint_artifact_001` | Pico-inspired synthetic | resume smoke | n/a | n/a | downgraded smoke in v1 |
| `agentic_native_readonly_exploration_001` | Pico-inspired synthetic | read-only smoke | n/a | n/a | downgraded smoke in v1 |
| `agentic_native_approval_001` | Pico-inspired synthetic | tool_policy | n/a | n/a | drafted in v1 |
| `agentic_native_sandbox_001` | Pico-inspired synthetic | sandbox | n/a | n/a | drafted in v1 |
| `agentic_native_long_output_001` | synthetic | evidence | n/a | n/a | drafted in v1 |

## Acceptance Criteria

- no-key CI pass
- task quality pass
- executable quality pass for new core tasks
- live smoke run completed for new core tasks
- agentic-native v1 live smoke completed or failures classified
- Phase 3C failure triage complete
- Phase 3C failure stability rerun complete
- agentic-native memory evidence blocker fixed or explicitly quarantined
- dogfood-derived provenance is not overclaimed; v0.3 has no release-grade
  dogfood-derived task until source commits or reference patches are recorded

## Non-Goals

- Do not claim public leaderboard readiness.
- Do not modify hidden tests to improve pass rate.
- Do not fabricate ablation results before runtime feature flags exist.
