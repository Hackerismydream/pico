# Phase 3C Stability-Sensitive Tasks

| Task | Original Full Run | Rerun 1 | Rerun 2 | Classification | Release Treatment |
|---|---|---|---|---|---|
| `core_029` | `tool_policy_violation` | pass | pass | stability-sensitive process failure | keep diagnostic, do not count as stable hidden-edge failure |
| `core_030` | `hidden_test_failure` | pass | `hidden_test_failure` | stability-sensitive hidden failure | keep but mark stability-sensitive |

Stable hidden-edge failures remain: `core_016`, `core_018`, `core_019`,
`core_023`, `core_027`, and `core_028`.
