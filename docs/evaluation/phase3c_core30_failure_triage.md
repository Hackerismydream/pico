# Phase 3C Core30 Failure Triage

Run: 2026-05-23 DeepSeek full 30-task core run

Source artifacts:

- summary: `/tmp/picobench-20260523-core30/summary.json`
- task results: `/tmp/picobench-20260523-core30/task_results.jsonl`
- failure reports: `/tmp/picobench-20260523-core30/failures/`
- evidence: `/tmp/picobench-20260523-core30/evidence/`

Policy: do not modify hidden tests to improve pass rate. Hidden expectations may
only change if the expectation is proven wrong against the task contract.

| Task | Category | Public | Hidden | Process | Evidence | Decision | Reason |
|---|---|---:|---:|---:|---:|---|---|
| `core_016` | `hidden_test_failure` | 1 | 0 | 1 | 1 | keep as benchmark signal | Public JSON filtering passed, but hidden numeric-string coercion failed. The edge is task-valid and not a runner issue. |
| `core_018` | `hidden_test_failure` | 1 | 0 | 1 | 1 | keep as benchmark signal | Public todo parsing passed, but hidden whitespace trimming failed. This is a useful parser edge. |
| `core_019` | `hidden_test_failure` | 1 | 0 | 1 | 1 | keep as benchmark signal | Public URL joins passed, but hidden empty-path normalization kept an unwanted trailing slash. |
| `core_023` | `hidden_test_failure` | 1 | 0 | 1 | 1 | keep as benchmark signal | Public table formatting passed, but hidden `None` cell rendering failed. Hidden expectation is consistent with empty-cell semantics. |
| `core_027` | `hidden_test_failure` | 1 | 0 | 1 | 1 | keep as benchmark signal | Same frontmatter/tag edge previously seen in Phase 3B; stable pressure task unless later stability rerun contradicts it. |
| `core_028` | `hidden_test_failure` | 1 | 0 | 1 | 1 | keep as benchmark signal | Redaction edge failed on blank-token audit behavior. Do not weaken hidden tests; this is exactly the security edge. |
| `core_029` | `tool_policy_violation` | 1 | 1 | 0 | 1 | keep as benchmark signal | Functional behavior passed, but strict process failed because `config.py` was written before the exact target was read. Validator is working. |
| `core_030` | `hidden_test_failure` | 1 | 0 | 1 | 1 | keep as benchmark signal | Scheduler treated implicit dependency-only nodes as a cycle. Hidden expectation matches DAG scheduler semantics. |

## Decision Summary

All 8 failures remain benchmark signal after triage. No hidden test change is
justified by the 2026-05-23 evidence. `core_029` is intentionally a strict
process failure, not a product/runtime bug.
