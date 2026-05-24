# PicoBench v0.3 Results Summary

Status: release-candidate hardening in progress.

## Task Count

| Suite | Count | Notes |
|---|---:|---|
| L0 runtime regression | 2 | deterministic runtime tasks |
| L2 core coding | 40 | `core_001`-`core_040` |
| L1 v3 human-gate delegated | 12 | unchanged from v0.2 |
| L3 agentic-native v1 | 8 | v0 tasks plus 5 native smoke scenarios; true resume/subagent coverage remains draft/quarantined |
| Live/agent total | 60 | core + human-gate + agentic-native |

## Completed Checks

| Check | Result | Artifact |
|---|---|---|
| `agentic_native_memory_001` rerun | 3/3 agentic-native v0 strict pass, evidence consistency `1.0` | `/tmp/picobench-agentic-native-rerun2/summary.json` |
| New core executable quality | 10/10 task subset passed | `/tmp/picobench-quality-new10.json` |
| Phase 3C core30 triage | complete | `docs/evaluation/phase3c_core30_failure_triage.md` |
| Phase 3C failure stability | complete; attempts passed 2/8 and 1/8 strict, both evidence consistency `1.0` | `/tmp/picobench-phase3c-failures-rerun-1`, `/tmp/picobench-phase3c-failures-rerun-2` |
| Latest HEAD no-key gates | passed: `271 passed, 2 skipped, 6 warnings`; task quality 40/40; L0 runtime 2/2 | `/tmp/picobench-latest-quality.json`, `/tmp/picobench-latest-runtime` |
| New core live smoke | complete; 9/10 strict pass, evidence consistency `1.0` | `/tmp/picobench-v03-new-core-a`, `/tmp/picobench-v03-new-core-b` |
| Agentic-native v1 final verification | revised suite passed 8/8 strict, evidence consistency `1.0` | `/tmp/picobench-v03-final-agentic-native-7218d68` |
| GitHub Actions for `2c7b9df` | success; run id `26351780359`; artifact id `7182157242` | `https://github.com/Hackerismydream/pico/actions/runs/26351780359` |

## Readiness

PicoBench has the intended v0.3 task surface: 60 live/agent tasks. After
provenance cleanup, quality metadata rationale, CI confirmation, and revised
agentic-native v1 verification, it can be treated as a v0.3 release candidate.
It should not be called final v0.3 release: v0.3 has no auditable
dogfood-derived tasks after provenance cleanup, true two-pass resume is not
implemented, and true subagent evidence is quarantined.

## Failures To Carry Forward

| Area | Failure | Decision |
|---|---|---|
| New core | `core_032` hidden manifest edge | keep as benchmark signal unless prompt is proven underspecified |
| Agentic-native v1 | `agentic_native_checkpoint_artifact_001` | downgraded to checkpoint artifact smoke; not release-grade resume coverage |
| Agentic-native v1 | `agentic_native_subagent_001` | quarantined; replaced by `agentic_native_readonly_exploration_001` smoke |
| Dogfood provenance | no auditable `pico-dogfood-derived` tasks | do not claim dogfood-derived coverage until real source commits or patches exist |

# PicoBench v0.3 Final Review Summary

## Status

- [x] v0.3 review candidate
- [x] v0.3 release candidate
- [ ] final v0.3 release

## Task Surface

| Suite | Count | Release-grade | Draft/Quarantined |
|---|---:|---:|---:|
| Core coding | 40 | 40 | 0 |
| v3 human-gate delegated | 12 | 12 delegated gate scenarios | 0 |
| Agentic-native v1 | 8 | 8 smoke/native tasks | true resume and true subagent coverage are not release-grade |

## Provenance

| Source Type | Count | Notes |
|---|---:|---|
| `synthetic` | 38 core/agentic-native tasks | ordinary benchmark-authored tasks |
| `pico-inspired-synthetic` | 10 core/agentic-native tasks | inspired by Pico mechanisms but not traceable to source commits |
| `pico-dogfood-derived` | 0 | no v0.3 task currently has source commit or reference patch provenance |

## Evidence

| Suite | Evidence Mode | Evidence Consistency |
|---|---|---|
| Core / agentic-native | `native` | calculated from `report_trace_session_consistency` |
| v3 human-gate | `delegated_human_gate` | `not_applicable` |
| Mixed reports | `mixed` | native tasks only; delegated rows display `n/a` |

## Blockers

| Blocker | Status | Decision |
|---|---|---|
| Dogfood provenance | fixed by reclassifying unsupported labels | no dogfood-derived claim in v0.3 |
| True resume benchmark | not implemented | checkpoint artifact smoke only |
| True subagent benchmark | quarantined | do not count read-only smoke as subagent coverage |
| `core_029` / `core_030` stability | documented | keep diagnostic; do not mix with stable hidden failures |
| Revised agentic-native v1 final rerun | complete | 8/8 strict pass, evidence consistency `1.0` |

## Recommendation

Promote to v0.3 release candidate. Do not accept as final v0.3 release yet.
Final release still requires real dogfood-derived tasks with source commits or
reference patches, true two-pass resume coverage, and true subagent event
coverage.
