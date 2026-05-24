# PicoBench v0.3 Results Summary

Status: candidate in progress.

## Task Count

| Suite | Count | Notes |
|---|---:|---|
| L0 runtime regression | 2 | deterministic runtime tasks |
| L2 core coding | 40 | `core_001`-`core_040` |
| L1 v3 human-gate delegated | 12 | unchanged from v0.2 |
| L3 agentic-native v1 | 8 | v0 tasks plus 5 new native scenarios |
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
| Agentic-native v1 live smoke | complete; 6/8 strict pass, evidence consistency `1.0` | `/tmp/picobench-v03-agentic-native` |

## Readiness

PicoBench now has the intended v0.3 task surface: 60 live/agent tasks, and the
required no-key, quality, stability, and live-smoke checks have been recorded.
It is not ready to call final v0.3 release because `agentic_native_resume_001`
and `agentic_native_subagent_001` need task-design/runtime follow-up before the
native v1 suite is release-grade. It is ready for a v0.3 review run.

## Failures To Carry Forward

| Area | Failure | Decision |
|---|---|---|
| New core | `core_032` hidden manifest edge | keep as benchmark signal unless prompt is proven underspecified |
| Agentic-native v1 | `agentic_native_resume_001` public/changed-path failure | fix task contract or implement true resume harness before release |
| Agentic-native v1 | `agentic_native_subagent_001` step budget and missing report | increase budget or replace drafted subagent proxy with real subagent event once supported |
