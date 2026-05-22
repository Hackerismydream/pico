# PicoBench Ablation Status

The current branch records ablation variants as `planned_only`.

Implemented output:

- `pico-full`
- `pico-no-memory`
- `pico-no-plan`
- `pico-no-subagent`
- `pico-no-skills`

Current limitation: Pico does not yet expose stable runtime feature flags for
turning memory, plan mode, subagents, or skills off in an otherwise identical
public CLI run. The ablation script therefore writes an explicit planned summary
instead of pretending to run an experiment.

Command:

```bash
uv run python scripts/run_picobench_ablation.py \
  --suite core \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --output-dir /tmp/picobench-ablation-plan \
  --plan-only
```

Ablation becomes runnable only after feature flags are added deliberately to the
product/runtime boundary.
