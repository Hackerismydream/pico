# TokenWise cost experiment contract

> **Status: live runner ready; paid campaign not run.** PicoBench freezes the
> treatment arms, workload shapes, sealed task corpus, reduction formulas, and
> positive-claim gates. The credential-free model and price preflight passes,
> but this checkout has no OpenRouter credential, so the paid cache preflight
> and formal campaign have not run. This document therefore contains no current
> product result.

## Question

Does TokenWise reduce the estimated API cost of a verified successful Agent
task, compared with both no explicit prompt-cache markers and Provider
automatic caching, without reducing task success?

The experiment does not claim that caching reduces the logical prompt size.
It measures how Provider usage is reclassified among fresh input, cache write,
and cache read tokens, then prices those categories from a frozen model price
snapshot.

## Treatment axis

Every Comparison Block executes the same task once under each cache policy.
`cache_policy` is the only declared treatment axis.

| Policy | Request behavior | Role |
| --- | --- | --- |
| `no_explicit_cache` | Disable Provider auto-cache and install no cache TokenStrategy | Primary control |
| `provider_auto` | Enable the Provider adapter's automatic cache placement | External baseline |
| `system_and_3` | Cache the system prefix and last three messages | Diagnostic reference |
| `tokenwise_adaptive_4` | Cache tools, system prefix, and the rolling message tail with at most four breakpoints | Treatment |

The Provider, exact model, generation settings, Tool set, Context budget,
workspace fixture, prompt bytes, and retry limits remain identical. Fallbacks
are forbidden. Each policy uses an isolated cache namespace of equal byte
length so one arm cannot warm another arm's cache.

## Frozen workload matrix

The formal plan has four workload classes, three cases per class, and three
repetitions:

| Workload class | Observable pressure | Shape per Trial |
| --- | --- | --- |
| `stable_dialogue` | Repeated stable system instructions | Six short Turns, no Tools |
| `long_history` | Growing conversation prefix | Six Turns after sixteen seeded history Turns |
| `tool_accumulation` | Tool schemas and results accumulate across Turns | Six Turns, one verified Tool call per Turn |
| `intra_turn_tool_chain` | New Tool results extend the prefix within one Turn | One Turn with a three-step verified Tool chain |

This produces 36 Comparison Blocks and 144 Trials. Four declared comparisons
per block produce 144 Pair Results. A Trial is one policy executing one case
once; it is not a workload and it is not a whole four-arm comparison.

Before the formal run, a disjoint calibration corpus must prove the live
runner, cache isolation, Provider usage fields, and Verifiers. Calibration
results cannot enter the formal report.

The formal route is pinned to `anthropic/claude-sonnet-5` through OpenRouter's
Anthropic endpoint with Provider fallback disabled. The frozen 2026-08-06
price snapshot is USD 2.00 per million fresh input tokens, USD 10.00 per
million output tokens, USD 0.20 per million cache-read tokens, and USD 2.50
per million five-minute cache-write tokens. Any catalog price drift aborts the
campaign before a paid call.

## Trial procedure

For each Comparison Block:

1. Materialize four byte-identical workspaces from one sealed fixture.
2. Assign an equal-length cache namespace to each arm and rotate arm order
   deterministically from the plan digest.
3. Build the Agent Loop with the arm's explicit StrategyRegistry and submit
   every Turn through the Agent Turn Runner.
4. Record every Provider call, including retries and final synthesis, with the
   requested model, actual model, fresh input, cache write, cache read, output,
   and raw Provider usage.
5. Run the parent-owned deterministic Verifier after the Trial. Model text is
   never accepted as proof of task completion.
6. Preserve Provider, infrastructure, timeout, cancellation, and task
   failures as terminal records. Do not drop an expensive failed Trial.

All requests in a block must finish inside the frozen cache TTL. A separate
negative probe deliberately crosses the TTL and must show a new cache write;
that probe diagnoses cache semantics and does not enter the formal cost result.

## Metrics

The primary metric is estimated cost per verified success:

```text
cost_per_verified_success = sum(all valid Trial cost) / verified successes
```

Failed tasks remain in the numerator. This prevents an arm from looking cheap
by failing early.

The conservative cache hit rate is:

```text
cache_read / (fresh_input + cache_write + cache_read)
```

The cold first call and every rewrite stay in the denominator. A served-hit
rate that removes cache writes may be reported as a diagnostic, but it cannot
replace the conservative rate in a resume claim.

The report also includes task pass rate, fresh input per verified success,
cache write-to-read ratio, Provider calls per task, and end-to-end latency.
Cost is rebuilt from raw usage and a digest-bound price snapshot. It is an
estimate unless reconciled against a Provider invoice.

## Validity and claim gates

A Comparison Block is valid only when all four arms have terminal records,
complete usage and cost fields, the same requested and actual model, no
fallback, unchanged fixtures, and an external Verifier result.

Positive resume metrics are exported only when:

- all 36 planned Comparison Blocks are valid;
- all four workload classes are represented;
- TokenWise task pass rate is no lower than both primary baselines in every
  workload class;
- TokenWise cost per verified success is lower than both no explicit cache and
  Provider auto-cache;
- raw records rebuild the same report byte for byte.

If any gate fails, `cv_metrics` is empty. A cheaper but less successful policy
is a negative product result, not a cost-optimization claim.

## Required negative probes

The credential-free and calibration gates must cover:

- a prefix below the Provider's cacheable minimum;
- cache expiry across the configured TTL;
- a changed system prompt;
- a changed Tool Schema;
- Provider routing or fallback drift;
- missing cache usage fields;
- cache writes with zero subsequent reads;
- a task-success regression despite lower token cost.

These probes explain why a cache misses or becomes more expensive. They do not
inflate the formal Trial denominator.

The live preflight executes the cache-minimum, namespace-isolation, changed
system, changed Tool Schema, exact-model, usage-completeness, and five-minute
expiry probes. The expiry probe waits for the configured TTL and must observe
a new cache write. OpenRouter response caching is disabled so a response-cache
hit cannot zero the Provider usage being measured.

## Live execution

The dedicated runner is resumable and freezes each Trial record before moving
to the next arm. It stops before a new Provider call at either 1,200 calls or
USD 25 of observed spend. Failed tasks and Provider attempts remain in the
artifact numerator.

```bash
uv run python -m benchmarks.picobench.tokenwise_cost_campaign \
  --mode preflight \
  --execute-paid-campaign

uv run python -m benchmarks.picobench.tokenwise_cost_campaign \
  --mode formal \
  --execute-paid-campaign
```

The runner reads `OPENROUTER_API_KEY`, then falls back to the configured
`providers.openrouter.apiKey`. It never writes the credential into campaign
artifacts. Raw Trial and per-call records live under
`.pico/evidence/tokenwise-cost/`; the final report is rebuilt only from those
terminal records.

## Current evidence boundary

The Pack at `benchmarks/picobench/packs/tokenwise_cost/` proves the matrix,
Pair definitions, conservative hit-rate formula, success-normalized cost, and
fail-closed claim reduction. Its generic `run_trial` method remains an
infrastructure failure so an ordinary PicoBench campaign cannot accidentally
spend money. The dedicated `tokenwise_cost_campaign` entry point owns the paid
route, sealed corpus, preflight, resume behavior, and cost ceiling.

No eligible credential was available at this evidence capture. Current
evidence therefore stops at runner implementation plus the credential-free
catalog and price check.
