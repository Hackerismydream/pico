# PicoBench Live Results Summary

## Latest run

- date: 2026-05-24
- commit: `3bf2b2ddac7f84cf91592c444524f403fa08626c`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `agentic-native`
- tasks: 8 revised `picobench-agentic-native-v1` tasks
- strict_pass_rate: `1.0`
- failures: none

## Results by suite

| Suite | Tasks | Strict passed | Strict failed | Skipped | Pass rate |
|---|---:|---:|---:|---:|---:|
| agentic-native v1 final verification 2026-05-24 | 8 | 8 | 0 | 0 | 1.0 |
| agentic-native v1 live 2026-05-24 | 8 | 6 | 2 | 0 | 0.75 |
| v0.3 new core live 2026-05-24 | 10 | 9 | 1 | 0 | 0.9 |
| Phase 3C failure stability attempt 2 | 8 | 1 | 7 | 0 | 0.125 |
| Phase 3C failure stability attempt 1 | 8 | 2 | 6 | 0 | 0.25 |
| agentic-native v0 evidence rerun 2026-05-24 | 3 | 3 | 0 | 0 | 1.0 |
| core full live 2026-05-23 | 30 | 22 | 8 | 0 | 0.733 |
| agentic-native live 2026-05-23 | 3 | 2 | 1 | 0 | 0.667 |
| agentic v3 gate live 2026-05-23 | 12 | 12 | 0 | 0 | 1.0 |
| core live smoke `core_001` | 1 | 1 | 0 | 0 | 1.0 |
| core live smoke multi-file | 5 | 2 | 3 | 0 | 0.4 |
| agentic-native live smoke | 3 | 3 | 0 | 0 | 1.0 |
| core Phase 3B 10-task subset | 10 | 8 | 2 | 0 | 0.8 |

## Latest Failure Taxonomy

| Category | Count | Notes |
|---|---:|---|
| `hidden_test_failure` | stable core: 12; stability-sensitive: 1; new core: 1 | Stable Phase 3C failures are `core_016`, `core_018`, `core_019`, `core_023`, `core_027`, `core_028` across two reruns. `core_030` is stability-sensitive and `core_032` is a new-core hidden edge. |
| `public_test_failure` | 1 historical v1 smoke | Previous `agentic_native_resume_001` failed before downgrade to `agentic_native_checkpoint_artifact_001`; revised suite rerun passed 8/8 |
| `step_budget_exceeded` | 1 historical v1 smoke | Previous `agentic_native_subagent_001` failed and is quarantined; revised read-only exploration smoke rerun passed 8/8 |
| `tool_policy_violation` | 1 historical full-core run | Original full-core `core_029` failure; targeted reruns passed, so it is stability-sensitive and not a stable hidden-edge failure |
| `trace_report_inconsistent` | 0 | `agentic_native_memory_001` evidence blocker fixed in rerun: 3/3 strict pass, evidence consistency `1.0` |

## Notes

- Not a public leaderboard.
- Hidden tests are not published.
- Results are provider/model/config specific.
- Live artifacts are stored under `/tmp/picobench-live-smoke-core001`,
  `/tmp/picobench-live-smoke-multifile`, and
  `/tmp/picobench-live-smoke-agentic-native` on the runner machine.
- Phase 3B artifacts are stored under `/tmp/picobench-phase3b-core10`.
- 2026-05-23 full-run artifacts are stored under
  `/tmp/picobench-20260523-core30`,
  `/tmp/picobench-20260523-agentic-native`, and
  `/tmp/picobench-20260523-agentic-v1`.
- 2026-05-24 v0.3 artifacts are stored under
  `/tmp/picobench-agentic-native-rerun2`,
  `/tmp/picobench-phase3c-failures-rerun-1`,
  `/tmp/picobench-phase3c-failures-rerun-2`,
  `/tmp/picobench-v03-new-core-a`,
  `/tmp/picobench-v03-new-core-b`, and
  `/tmp/picobench-v03-agentic-native`.
- Revised agentic-native v1 final verification is stored under
  `/tmp/picobench-v03-final-agentic-native-7218d68`: 8/8 strict pass, evidence
  consistency `1.0`.
- Current HEAD no-key verification passed locally on 2026-05-24:
  `uv run pytest tests/ -q` reported `271 passed, 2 skipped, 6 warnings`;
  task quality reported 40 tasks and 40 hidden fixtures with no issues; L0
  runtime passed 2/2.
- Delegated human-gate evidence is now reported with
  `evidence_mode=delegated_human_gate` and evidence consistency
  `not_applicable` instead of `0.0` in newly generated report cards.
- Mixed native/delegated reports calculate evidence consistency only over
  native tasks; delegated rows show `n/a`.
- GitHub Actions run for `2c7b9df25843444bb58a10f49fa580b63b3b713c` passed:
  run id `26351780359`, artifact id `7182157242`.
- Previous 2026-05-22 GitHub Actions run `26271849474` passed for `068318f`.
