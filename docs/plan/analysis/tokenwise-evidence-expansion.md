# TokenWise DeepSeek evidence expansion

> **Status: proposed.** This document records the current CV-eligible result
> and a larger follow-up campaign. It does not authorize implementation or paid
> Provider calls. Execution requires an accepted GitHub issue with an explicit
> cost ceiling.

## Decision

The completed DeepSeek campaign is valid TokenWise evidence. TokenWise owns
Provider-aware cache usage normalization, model-specific cost reconstruction,
the paired experiment, and the claim gates. DeepSeek owns the automatic prefix
cache itself.

The result is more than a Provider adapter, but it is not evidence for
Anthropic-style explicit cache breakpoints. The current treatment compares
Pico's ordinary stable request prefix with a benchmark-only prefix disruption
counterfactual.

## Current evidence

The commit-bound campaign in
[`docs/evaluation/tokenwise-cost.md`](../../evaluation/tokenwise-cost.md)
completed:

| Dimension | Result |
| --- | ---: |
| Workload classes | 4 |
| Frozen cases per class | 3 |
| Repetitions per case | 3 |
| Comparison Blocks | 36 |
| Trials | 72 |
| Real Provider calls | 504 |
| Stable-prefix conservative cache hit rate | 75.19% |
| Estimated cost per verified success, disrupted | USD 0.008694 |
| Estimated cost per verified success, stable | USD 0.002309 |
| Estimated cost reduction | 73.44% |
| Task pass rate, both arms | 100% |

Seventy-two Trials are sufficient for a CV claim because the unit of evidence
is 36 paired Comparison Blocks, not 72 unrelated samples. The 504 real
Provider calls also exercise multi-Turn and Tool-call behavior within each
Trial. The main weakness is narrower per-workload coverage: each class has
only nine paired blocks.

## CV wording

Recommended concise wording:

> 设计 TokenWise Provider-aware 缓存记账与成本评估机制；通过稳定系统指令、工具定义和滚动历史的请求前缀，实现 75.19% 保守缓存命中率，单位成功任务估算成本降低 73.44%。

This wording is eligible when interpreted as the combined behavior of
TokenWise's Provider-aware accounting and Pico's stable request prefixes. It
must not be expanded into any of the following unsupported claims:

- TokenWise reduced the logical input-token count by 75.19%.
- TokenWise created DeepSeek's automatic cache.
- Pico placed up to four explicit cache breakpoints.
- The result was measured against a previous production version.
- The estimated cost was reconciled against a Provider invoice.

For an evidence-heavy version, add the comparison boundary:

> 设计 TokenWise Provider-aware 缓存记账与成本评估机制；在 4 类固定 Agent workload 中，通过稳定系统指令、工具定义和滚动历史的请求前缀，实现 75.19% 保守缓存命中率，单位成功任务估算成本较逐调用扰动反事实降低 73.44%，两组任务通过率均为 100%。

## Why expand

Increasing repetitions alone would mostly measure Provider variance on the
same prompts. The follow-up should increase task diversity first, then add
enough repetitions to estimate uncertainty.

The larger campaign is intended to:

1. increase per-workload case coverage;
2. estimate confidence intervals over paired blocks;
3. report distributional results instead of only aggregate weighted means;
4. preserve the exact task-success and model-routing gates from the completed
   campaign;
5. determine whether the overall result is shared across all four workload
   classes rather than dominated by one class.

## Proposed 320-Trial matrix

| Axis | Value |
| --- | --- |
| Workload classes | `stable_dialogue`, `long_history`, `tool_accumulation`, `intra_turn_tool_chain` |
| Frozen cases | 8 per workload class, 32 total |
| Repetitions | 5 per case |
| Arms | `prefix_disrupted`, `prefix_stable` |
| Comparison Blocks | `4 * 8 * 5 = 160` |
| Trials | `160 * 2 = 320` |

Each Comparison Block runs the same case and repetition under both arms. Arm
order remains deterministically rotated. Every Trial receives an isolated
DeepSeek `user_id` so cache warming cannot cross arms or blocks.

The 32 cases must be frozen before the formal run. New cases should vary Turn
count, seeded-history length, Tool-result size, Tool-chain depth, and stable
system-prompt size while preserving deterministic output and Tool-call
verification. Reusing private user histories requires separate consent; the
default corpus remains synthetic and repository-owned.

## Metrics and statistical analysis

The primary metric remains:

```text
cost_per_verified_success = total estimated cost / verified successes
```

The conservative cache hit rate remains:

```text
cache_read / (cache_miss + cache_read)
```

The expanded report should add:

- paired absolute and relative cost differences for every Comparison Block;
- median, P25, and P75 of paired cost reduction;
- a workload-stratified paired bootstrap 95% confidence interval using 10,000
  resamples of Comparison Blocks;
- overall and per-workload cache hit rate, cost per verified success, and task
  pass rate;
- the number of valid, excluded, and failed blocks with typed reasons.

The bootstrap procedure, random seed, aggregation weights, and exclusion rules
must be frozen in the campaign manifest before any paid formal Trial runs.

## Claim gates

No positive CV metric is exported unless all of these gates pass:

1. all 160 planned Comparison Blocks are present and valid;
2. every Provider call satisfies `prompt = cache_hit + cache_miss`;
3. the exact requested DeepSeek model serves every call;
4. no fallback or route drift occurs;
5. every workload class has all eight cases and five repetitions;
6. stable-prefix task pass rate does not regress overall or within any
   workload class;
7. stable prefixes improve conservative cache hit rate and estimated cost per
   verified success;
8. the paired 95% confidence interval for cost reduction excludes zero;
9. raw Trial artifacts, manifest digests, price snapshot, code commit, and
   reducer output reconcile.

Failed tasks remain in the cost numerator. A Provider failure, incomplete
usage record, or missing pair invalidates its Comparison Block and therefore
fails the complete-campaign claim gate.

## Estimated execution budget

The completed 72-Trial campaign used 504 Provider calls and an estimated USD
0.3961. Linear scaling gives an initial planning estimate of approximately:

```text
320 / 72 * 504 = 2,240 Provider calls
320 / 72 * USD 0.3961 = USD 1.76
```

Provider-call count and cost vary with model Tool behavior, so the formal
campaign should use a maximum of 2,600 calls and a USD 3 hard ceiling. These
figures are planning limits, not paid-run authorization.

## Delivery decomposition

| Slice | Main paths | Completion evidence |
| --- | --- | --- |
| Corpus expansion | `benchmarks/picobench/tasks/tokenwise_cost/formal.json` | 32 frozen cases and deterministic corpus digest |
| Campaign contract | `benchmarks/picobench/packs/tokenwise_cost/live.py` | 8 cases, 5 repetitions, frozen budget and analysis settings |
| Runtime integration | `benchmarks/picobench/packs/tokenwise_cost/runner.py` | isolated paired execution against the real DeepSeek Provider |
| Statistical reducer | `benchmarks/picobench/packs/tokenwise_cost/reducer.py` | paired distribution metrics and stratified bootstrap CI |
| CLI and resume | `benchmarks/picobench/tokenwise_cost_campaign.py` | preflight, resumable artifacts, hard ceilings, fail-closed resume |
| Verification | `tests/test_picobench_tokenwise_cost*.py` | deterministic contract, failure, resume, and reducer tests |
| Evidence reconciliation | `docs/evaluation/tokenwise-cost.md` | commit-bound final report and updated claim boundary |

Integration must verify the real chain rather than isolated modules:

```text
frozen corpus
  -> campaign planner
  -> AgentLoop and TokenWise strategies
  -> DeepSeek usage normalization
  -> model-specific cost reconstruction
  -> retained Trial artifacts
  -> paired reducer and claim gate
  -> CV-eligible metrics
```

## Execution sequence

1. Open and accept a GitHub issue that fixes scope, DeepSeek model, Provider
   credential boundary, and the USD 3 cumulative ceiling.
2. Freeze the 32-case corpus and statistical-analysis manifest.
3. Implement deterministic corpus, reducer, resume, and failure-gate tests.
4. Run credential-free checks and a paid four-call cache preflight.
5. Execute the 320-Trial campaign once, resuming only from matching manifest
   and code digests.
6. Rebuild the report from retained Trial artifacts and run the independent
   claim gate.
7. Update CV wording only if every claim gate passes. Otherwise retain the
   current 72-Trial result and report the larger campaign as ineligible.

## Separate Anthropic experiment

Anthropic-style explicit cache breakpoints remain a different future
experiment. Its proposed four arms are no explicit cache, Provider automatic
behavior, fixed system-plus-history breakpoints, and adaptive TokenWise
breakpoints. Results from that experiment must not be combined with the
DeepSeek two-arm numbers because the Provider cache controls and pricing
semantics differ.
