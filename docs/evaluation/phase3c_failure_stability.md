# Phase 3C Failure Stability

Targeted rerun scope:

- `core_016`
- `core_018`
- `core_019`
- `core_023`
- `core_027`
- `core_028`
- `core_029`
- `core_030`

Commands:

```bash
uv run python scripts/run_picobench.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_016 --task core_018 --task core_019 --task core_023 \
  --task core_027 --task core_028 --task core_029 --task core_030 \
  --output-dir /tmp/picobench-phase3c-failures-rerun-<n> \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --json
```

| Attempt | Task | Strict | Functional | Failure Category | Same Failure as Core30? | Evidence Consistency | Decision |
|---|---|---:|---:|---|---:|---:|---|
| 1 | `core_016` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 1 | `core_018` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 1 | `core_019` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 1 | `core_023` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 1 | `core_027` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 1 | `core_028` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 1 | `core_029` | 1 | 1 | none | 0 | 1.0 | mark stability-sensitive |
| 1 | `core_030` | 1 | 1 | none | 0 | 1.0 | mark stability-sensitive |
| 2 | `core_016` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 2 | `core_018` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 2 | `core_019` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 2 | `core_023` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 2 | `core_027` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 2 | `core_028` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal |
| 2 | `core_029` | 1 | 1 | none | 0 | 1.0 | mark stability-sensitive |
| 2 | `core_030` | 0 | 0 | `hidden_test_failure` | 1 | 1.0 | keep as benchmark signal; also stability-sensitive |

## Result

- Attempt 1: 8 tasks, 2 strict pass, 6 strict failure, pass rate `0.25`,
  evidence consistency `1.0`.
- Attempt 2: 8 tasks, 1 strict pass, 7 strict failure, pass rate `0.125`,
  evidence consistency `1.0`.
- Stable failures across both targeted reruns: `core_016`, `core_018`,
  `core_019`, `core_023`, `core_027`, `core_028`.
- Stability-sensitive failures: `core_029` passed both targeted reruns after
  failing the original full core run on process policy; `core_030` passed
  attempt 1 but failed attempt 2 and the original full core run.

## Interpretation Rules

- If a task fails in the same way across reruns and the task contract is valid,
  keep it as benchmark signal.
- If a task flips between pass/fail, classify it as stability-sensitive and
  inspect whether the prompt is underspecified.
- If functional behavior passes but strict evidence/process fails, fix evidence
  or process only when the validator is wrong.
- Do not edit hidden tests unless the hidden expectation is proven incorrect.
