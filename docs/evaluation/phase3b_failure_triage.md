# Phase 3B Failure Triage

Run: 2026-05-22 DeepSeek 10-task core subset

- commit: `068318fea6d5aee29353656464c598667f678466`
- branch: `codex/picobench-v3`
- output_dir: `/tmp/picobench-phase3b-core10`
- strict_pass_rate: `0.8`
- failures: `core_027`, `core_028`

| Task | Strict | Functional | Failure category | Evidence path | Suspected cause | Decision |
|---|---:|---:|---|---|---|---|
| `core_001` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_001-run1` | none | Keep in Phase 3B baseline |
| `core_003` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_003-run1` | none | Keep in Phase 3B baseline |
| `core_011` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_011-run1` | none | Keep in Phase 3B baseline |
| `core_017` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_017-run1` | none | Keep in Phase 3B baseline |
| `core_021` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_021-run1` | none | Keep in Phase 3B baseline |
| `core_026` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_026-run1` | none | Keep in Phase 3B baseline |
| `core_027` | 0 | 0 | `hidden_test_failure` | `/tmp/picobench-phase3b-core10/evidence/core_027-run1` | Model passed visible frontmatter tests but missed hidden edges for documents without frontmatter and empty tag filtering | Keep as benchmark signal; do not change task unless hidden expectations are proven wrong |
| `core_028` | 0 | 0 | `hidden_test_failure` | `/tmp/picobench-phase3b-core10/evidence/core_028-run1` | Model passed visible permission/redaction path but failed hidden blank-token audit behavior | Keep as benchmark signal; repeated failure confirms this task has useful edge-case pressure |
| `core_029` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_029-run1` | none | Keep in Phase 3B baseline |
| `core_030` | 1 | 1 | none | `/tmp/picobench-phase3b-core10/evidence/core_030-run1` | none in this run | Keep in Phase 3B baseline; previous Phase 3A tool-policy failure did not reproduce |

## Recommendation

- [ ] Ready for Phase 3C full 30-task core live run
- [x] Needs benchmark/task/runner fixes before Phase 3C
- [ ] Needs product/runtime bugfix before Phase 3C

Reason: the live path is working, but Phase 3B produced repeated hidden-edge
failures on `core_027` and `core_028`. Those are useful benchmark signal, not
runner failures. Before full 30, run at least one more 10-task subset or a
targeted rerun of the failed tasks to measure stability.
