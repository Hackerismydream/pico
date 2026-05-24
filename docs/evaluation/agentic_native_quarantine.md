# Agentic-Native Quarantine

| Task | Reason | Required Runtime/Event Support | Status |
|---|---|---|---|
| `agentic_native_subagent_001` | no real subagent event verifier; previous proxy task only asked for a report and failed live smoke with `step_budget_exceeded` | `subagent_started`, `subagent_completed`, `subagent_mode=explore`, read-only scope evidence, no business file changes | quarantined |

## Replacement Smoke

`agentic_native_readonly_exploration_001` remains in
`benchmarks/picobench-agentic-native-v1.yaml` as a read-only exploration report
smoke. It is not a true subagent benchmark and must not be counted as
release-grade subagent coverage.
