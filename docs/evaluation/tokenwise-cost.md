# DeepSeek TokenWise cost experiment

> **Status: completed on 2026-08-06.** The frozen DeepSeek V4 Flash campaign
> completed 36 valid Comparison Blocks and 72 Trials. All claim gates passed.

## Question

How much does DeepSeek's automatic disk context cache reduce the estimated API
cost of a verified successful Pico Agent task when the request prefix remains
stable?

DeepSeek ignores Anthropic `cache_control` markers. TokenWise therefore does
not place explicit breakpoints for this Provider. It normalizes DeepSeek's
`prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`, rebuilds cost from
the Provider's cache-hit, cache-miss, and output rates, and measures the value
of prefix stability.

## Treatment axis

Every Comparison Block executes the same task under two policies. DeepSeek's
automatic cache remains enabled in both arms.

| Policy | Request behavior | Role |
| --- | --- | --- |
| `prefix_disrupted` | Change the leading system and Tool Schema bytes before every Provider call | Negative control |
| `prefix_stable` | Preserve Pico's ordinary request prefix | Treatment |

The disrupted arm is an experimental counterfactual, not an earlier product
version and not a deployable configuration. Each Trial uses a separate
DeepSeek `user_id` so one arm cannot warm another arm's KV cache.

The Provider, exact model, non-thinking generation mode, Tool set, Context
budget, workspace fixture, prompts, and retry limits remain fixed. Fallbacks
are forbidden.

## Frozen workload matrix

The campaign has four workload classes, three cases per class, and three
repetitions:

| Workload class | Observable pressure | Shape per Trial |
| --- | --- | --- |
| `stable_dialogue` | Repeated stable system instructions | Six short Turns, no Tools |
| `long_history` | Growing conversation prefix | Six Turns after sixteen seeded history Turns |
| `tool_accumulation` | Tool schemas and results accumulate across Turns | Six Turns, one verified Tool call per Turn |
| `intra_turn_tool_chain` | Tool results extend the prefix within one Turn | One Turn with a verified three-step Tool chain |

This produces 36 Comparison Blocks and 72 Trials. A Trial is one policy
executing one case once. The campaign made 504 real Provider calls.

## Metrics and gates

The primary metric is estimated cost per verified success:

```text
cost_per_verified_success = sum(all valid Trial cost) / verified successes
```

Failed tasks remain in the numerator. The conservative cache hit rate is:

```text
cache_read / (cache_miss + cache_read)
```

The report exports CV metrics only when all planned blocks are valid, every
usage record satisfies `prompt = cache_hit + cache_miss`, the exact requested
model served every call, all four workload classes are present, treatment task
success does not regress, and stable prefixes improve both cache hit rate and
cost per verified success.

## Result

The campaign was pinned to `deepseek/deepseek-v4-flash`. The frozen pricing
snapshot was USD 0.14 per million cache-miss input tokens, USD 0.0028 per
million cache-hit input tokens, and USD 0.28 per million output tokens.

| Metric | Prefix disrupted | Prefix stable |
| --- | ---: | ---: |
| Valid Trials | 36 | 36 |
| Verified task pass rate | 100% | 100% |
| Conservative cache hit rate | 0% | 75.23% |
| Estimated cost per verified success | $0.008704 | $0.002308 |

Stable prefixes reduced estimated cost per verified success by **73.49%**
relative to the deliberately disrupted counterfactual. All 36 Comparison
Blocks were valid, no fallback or model drift occurred, and the full campaign
used an estimated USD 0.3964.

Per-workload treatment hit rates were 65.09% for stable dialogue, 75.81% for
long history, 79.29% for Tool accumulation, and 65.68% for the intra-Turn Tool
chain.

## Evidence boundary

The result proves that Pico's stable request prefixes benefit from DeepSeek's
automatic cache under the frozen workload and that TokenWise reconstructs
DeepSeek cache usage and estimated cost. It does not prove that Pico created
DeepSeek's cache, that every production workload will achieve a 75.23% hit
rate, or that the estimate has been reconciled against a Provider invoice.

The report and per-call artifacts are retained outside git under
`.pico/evidence/tokenwise-cost-deepseek-context-layout/`. The report digest is
`5635ad590eaaecc702152042d5b246d297842d86bbc446c241f54cd8f7f37051`.
Repository policy forbids committing standalone report artifacts.

## Reproduction

```bash
uv run python -m benchmarks.picobench.tokenwise_cost_campaign \
  --mode preflight \
  --output-root .pico/evidence/tokenwise-cost-deepseek-context-layout \
  --execute-paid-campaign

uv run python -m benchmarks.picobench.tokenwise_cost_campaign \
  --mode formal \
  --output-root .pico/evidence/tokenwise-cost-deepseek-context-layout \
  --execute-paid-campaign
```

The runner reads `DEEPSEEK_API_KEY`, then falls back to
`providers.deepseek.apiKey` in Pico's config. It never writes credentials into
artifacts. It stops before a new call at either 1,200 Provider calls or USD 2
of observed estimated spend.
