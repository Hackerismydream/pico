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

## Required Runtime Flags

These are the concrete switches needed before the variants can become real
measurements:

| Variant | Required CLI/runtime capability | Why it is not run yet |
|---|---|---|
| `pico-full` | Existing default public CLI run | This is already represented by normal PicoBench runs, not the ablation script |
| `pico-no-memory` | A public flag such as `--disable-memory` that disables memory recall, `/remember`, and auto-dream without changing other behavior | No stable flag exists |
| `pico-no-plan` | A public flag such as `--disable-plan-mode` that disables `/plan` and plan tool enforcement | No stable flag exists |
| `pico-no-subagent` | A public flag such as `--disable-subagents` that removes worker tools and worker prompt paths | No stable flag exists |
| `pico-no-skills` | A public flag such as `--disable-skills` that disables project/bundled skill loading and slash registration | No stable flag exists |

The ablation script must stay `planned_only` until those controls exist at the
same public CLI boundary used by normal PicoBench tasks.
