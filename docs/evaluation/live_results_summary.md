# PicoBench Live Results Summary

## Latest run

- date: 2026-05-22
- commit: `068318fea6d5aee29353656464c598667f678466`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `core`
- tasks: `core_001`, `core_003`, `core_011`, `core_017`, `core_021`, `core_026`, `core_027`, `core_028`, `core_029`, `core_030`
- strict_pass_rate: `0.8`
- failures: `core_027`, `core_028`

## Results by suite

| Suite | Tasks | Strict passed | Strict failed | Skipped | Pass rate |
|---|---:|---:|---:|---:|---:|
| core live smoke `core_001` | 1 | 1 | 0 | 0 | 1.0 |
| core live smoke multi-file | 5 | 2 | 3 | 0 | 0.4 |
| agentic-native live smoke | 3 | 3 | 0 | 0 | 1.0 |
| core Phase 3B 10-task subset | 10 | 8 | 2 | 0 | 0.8 |

## Failure taxonomy

| Category | Count | Notes |
|---|---:|---|
| `hidden_test_failure` | 4 | `core_027`, `core_028` exposed hidden edge misses in both Phase 3A multi-file smoke and Phase 3B core10 |
| `tool_policy_violation` | 1 | `core_030` passed functional tests but violated read-before-write |

## Notes

- Not a public leaderboard.
- Hidden tests are not published.
- Results are provider/model/config specific.
- Live artifacts are stored under `/tmp/picobench-live-smoke-core001`,
  `/tmp/picobench-live-smoke-multifile`, and
  `/tmp/picobench-live-smoke-agentic-native` on the runner machine.
- Phase 3B artifacts are stored under `/tmp/picobench-phase3b-core10`.
- Current HEAD no-key verification passed locally, and GitHub Actions run
  `26271849474` passed for `068318f`.
