# PicoBench Live Results Summary

## Latest run

- date: 2026-05-23
- commit: `2372068723af8b1c06b3e43362193e91fdbe3c41`
- provider: `deepseek`
- model: `deepseek-v4-pro`
- suite: `core`
- tasks: all 30 `picobench-core-v1` tasks
- strict_pass_rate: `0.7333333333333333`
- failures: `core_016`, `core_018`, `core_019`, `core_023`, `core_027`, `core_028`, `core_029`, `core_030`

## Results by suite

| Suite | Tasks | Strict passed | Strict failed | Skipped | Pass rate |
|---|---:|---:|---:|---:|---:|
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
| `hidden_test_failure` | 7 | 2026-05-23 full core exposed edge misses in numeric strings, trimming, URL normalization, `None` rendering, frontmatter, redaction, and implicit dependency nodes |
| `tool_policy_violation` | 1 | `core_029` passed functionally but violated read-before-write on `config.py` |
| `trace_report_inconsistent` | 1 | 2026-05-23 agentic-native memory task wrote memory but missed required evidence files in the copied evidence bundle |

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
- Current HEAD no-key verification passed locally on 2026-05-23:
  `uv run pytest tests/ -q` reported `267 passed, 2 skipped, 6 warnings`;
  task quality reported 30 tasks and 30 hidden fixtures with no issues; L0
  runtime passed 2/2.
- Previous 2026-05-22 GitHub Actions run `26271849474` passed for `068318f`.
