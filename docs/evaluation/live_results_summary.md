# PicoBench Live Results Summary

## Latest run

- date: 2026-05-22
- commit: `f7cdecc28060d2bef46240f380966976c2a99b09`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `agentic-native`
- tasks: `agentic_native_plan_001`, `agentic_native_skill_001`, `agentic_native_memory_001`
- strict_pass_rate: `1.0`
- failures: none

## Results by suite

| Suite | Tasks | Strict passed | Strict failed | Skipped | Pass rate |
|---|---:|---:|---:|---:|---:|
| core live smoke `core_001` | 1 | 1 | 0 | 0 | 1.0 |
| core live smoke multi-file | 5 | 2 | 3 | 0 | 0.4 |
| agentic-native live smoke | 3 | 3 | 0 | 0 | 1.0 |

## Failure taxonomy

| Category | Count | Notes |
|---|---:|---|
| `hidden_test_failure` | 2 | `core_027`, `core_028` exposed hidden edge misses |
| `tool_policy_violation` | 1 | `core_030` passed functional tests but violated read-before-write |

## Notes

- Not a public leaderboard.
- Hidden tests are not published.
- Results are provider/model/config specific.
- Live artifacts are stored under `/tmp/picobench-live-smoke-core001`,
  `/tmp/picobench-live-smoke-multifile`, and
  `/tmp/picobench-live-smoke-agentic-native` on the runner machine.
