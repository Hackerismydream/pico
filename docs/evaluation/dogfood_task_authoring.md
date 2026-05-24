# Dogfood Task Authoring

Dogfood tasks should come from real Pico development work, not synthetic
variants written only to increase task count.

## Flow

1. Select a real Pico commit, bugfix, or feature with a clear before/after.
2. Recover the pre-fix state as the visible fixture base.
3. Write a user-style prompt that describes the problem without revealing hidden
   tests.
4. Add public tests for the obvious expected behavior.
5. Add hidden tests for boundary behavior that should remain private.
6. Record the source commit or reference patch in task metadata.
7. Run the task-quality checker.
8. Run at least one live provider smoke.
9. Run 3 stability trials before promotion into a held-out or release suite.
10. Write a short task-quality note with failures and contamination risk.

## Required Files

```text
tests/fixtures/picobench/<name>/
tests/fixtures/picobench/<name>/tests/
tests/fixtures/picobench_hidden/<task_id>/hidden_tests/
```

## Required Metadata

- `metadata.source`: use `pico-dogfood-derived` only when the task has an
  auditable Pico source commit or reference patch; otherwise use
  `pico-inspired-synthetic`
- `metadata.source_commit`: original commit or reference patch id
- `metadata.contamination_risk`
- `metadata.issue_clarity`
- `metadata.test_coverage`

## Skeleton Helper

Use the scaffold helper to create directories and print a YAML/JSON-compatible
task stub:

```bash
uv run python scripts/build_picobench_dogfood_task.py \
  --task-id core_041 \
  --name real_pico_bugfix_name \
  --category bugfix \
  --source-commit <commit> \
  --prompt "Fix the real Pico bug described here, then run python -m pytest tests -q."
```

The helper does not automate task extraction. It only prevents missing fixture
directories, hidden-test directories, and required benchmark fields.
