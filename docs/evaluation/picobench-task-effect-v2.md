# PicoBench task-effect v2

> **Status: live calibration complete; measurement invalid; formal blocked.**
> GitHub
> Issue [#77](https://github.com/Hackerismydream/pico-harness/issues/77) owns
> the accepted credential-free contract. Issue
> [#79](https://github.com/Hackerismydream/pico-harness/issues/79) owns the
> installed campaign, immutable inputs, and separate paid authority. The final
> calibration produced no eligible task-effect, retrieval, or efficiency
> result, so the formal matrix did not run.

PicoBench task-effect v2 preserves the completed CodeCairn continuity tracer
and adds a separate experiment identity for realistic next-task effect. It asks
whether CodeCairn can improve verified repository-task outcomes or reduce
rediscovery effort when the same task remains independently solvable with
Memory disabled.

The only paired treatment axis is:

```text
control:   memory.backend = null
treatment: memory.backend = codecairn
```

The treatment does not receive an extra Tool, expected answer, token budget,
retry, timeout, or iteration allowance.

## Live calibration result

Issue #79 bound clean Pico commit
`d6ef6242cff0fac496954ee6d57d08f35831cae5`, CodeCairn commit
`555248eeb3d3a4acdfb7acd3c43f5e3bcdaf9e83`, their installed wheel digests,
and Stage C digest
`c1a1567d10e1b253069f6933157e38810aa3a0d48014a563f38e2e0e5a5e9d2d`.
CodeCairn remained immutable throughout the campaign.

The final calibration experiment
`6fbc169ee80ff29e7b8822e6a26992856706a69eab71853ba3e08338410ed11f`
recorded:

| Evidence | Result |
| --- | --- |
| Task Trials | 12/12 terminal; all 12 selected Trials were Provider failures |
| Task Pairs | 0/6 valid |
| Retrieval Cases | 10/10 terminal and measurable |
| Ship completion | `true` |
| Measurement validity | `false` |
| Retrieval, task-success, and efficiency claims | all ineligible |
| Formal matrix | not started because calibration failed its Gate |
| Cumulative Issue #79 charge | 1.29966592 CNY; no open reservations |

The retrieval observations are diagnostic only. They include Hit@5, Recall@5,
and MRR of 1.0, injected precision of 0.4, no stale or cross-repository
injection, and hard-negative injection in every case. They are not eligible
CV metrics because the task-effect measurement is invalid.

The report was rebuilt twice from immutable raw records with byte-stable
`summary.json`, `cv-metrics.json`, and `REPORT.md` outputs. Its report digest
is `a5e4f79acd756276eb1b714dfc7959ac0e1e84a209df60d7b8f916412e66cde3`.
Generated evidence remains outside Git. This result demonstrates the
fail-closed campaign and its Provider-contract boundary; it does not
demonstrate CodeCairn uplift or regression on repository tasks.

## Credential-free Stage A

Run the complete Stage A Gate with:

```bash
make picobench-codecairn-task-effect-smoke
```

The target validates:

- 24 formal repository tasks across fact rediscovery, experience reuse,
  stale/conflict, and irrelevant/no-Memory classes;
- at least six disjoint calibration tasks;
- four or more independently reset pinned repository fixtures;
- 100 formal retrieval cases covering positive facts, positive experience,
  hard negatives, stale Memory, and cross-repository Memory;
- the 96-Trial and 48-Pair deterministic formal matrix;
- parent-owned Verifiers, path policy, Tool receipts, and test-state checks;
- true Hit@5, macro per-query Recall@5, MRR, injected precision, and negative
  injection metrics;
- byte-stable offline report rebuild;
- v1 task, Pack, schema, report, and metric-meaning regressions.

The scripted Stage A runners do not resolve a Provider, CodeCairn service,
embedding model, reranker, web Tool, or other external service. The task
runner is a parent-side reference solver: it reads declarative capture recipes
from the Pack, derives structured results from the pinned fixture, and emits
the artifact and receipts needed to exercise verification. The retrieval
runner likewise emits definition-backed reference rankings. These runners
prove Pack loading, fixture reset, evidence accounting, Verifier behavior, and
deterministic reduction. They do not test autonomous repository discovery,
semantic retrieval, or causal Memory benefit.

## Frozen identities and matrix

The v2 schemas and Pack identities are separate from the retained v1 campaign:

```text
task schema:        pico.picobench.codecairn-task-effect.v2
retrieval schema:   pico.picobench.codecairn-retrieval-quality.v2
formal Pack:        codecairn-task-effect-v2
calibration Pack:   codecairn-task-effect-calibration-v2
retrieval suite:    codecairn-retrieval-quality-v2
```

The formal task matrix is:

```text
24 tasks
x 2 Memory variants
x 2 repetitions
= 96 Trials
= 48 Pairs
```

The formal retrieval suite contains exactly:

| Query class | Cases |
| --- | ---: |
| Positive repository fact | 30 |
| Positive execution experience | 20 |
| Hard negative | 20 |
| Stale or superseded | 15 |
| Cross-repository | 15 |
| **Total** | **100** |

Calibration task and retrieval identities are disjoint from the formal set.

## Verification boundary

Repository fixtures are parent-owned and reset before every Trial. Stage A
does not invoke a live Agent. Its parent-side reference solver can read the
declarative `reference_solution`; that recipe and the expected artifact would
remain outside a future Agent workspace. The fixture-local bounded checker is
visible in the repository and validates repository integrity plus the
deliverable's declared path and structure, without embedding expected result
values. The external parent-owned Verifier checks:

- the required output artifact and exact structured value;
- allowed and forbidden changed paths;
- required Tool receipts;
- the declared bounded test command and exit state;
- the fixture identity used by the Trial.

A Trial fails closed when any of those checks is missing or inconsistent. The
model's final text never decides task success.

Every stale/conflict task also owns a frozen parent-side transition. The Gate
materializes the prior revision, verifies the declared prior observation,
applies the bound transition, and checks a distinct evaluated-fixture digest
before exposing only the evaluated state to the task. A stale prompt without
this state transition is not a valid v2 task.

## Retrieval metric meanings

The v2 reducer keeps ranked retrieval and injected context distinct:

- `positive_hit_at_5` is the fraction of positive queries with any expected
  Memory in the first five ranked candidates;
- `positive_recall_at_5` computes Recall@5 independently for each positive
  query, then reports the arithmetic mean across those queries;
- `positive_mrr` uses the rank of the first expected Memory;
- `injected_precision` is relevant injected items divided by all injected
  items for positive queries;
- negative, stale, and cross-repository metrics report whether any item was
  injected;
- mean irrelevant items per hard-negative query is an item count, not a rate.

These fields do not reinterpret the retained v1 `Recall@5` or
irrelevant-injection fields.

## Independent campaign states

The v2 report keeps completion, validity, and positive claims independent:

```text
codecairn_task_effect_v2.ship_complete
codecairn_task_effect_v2.measurement_valid
codecairn_retrieval_v2.claim_eligible
codecairn_task_success_v2.claim_eligible
codecairn_efficiency_v2.claim_eligible
```

At least 44 of 48 formal Pairs must be valid, and every formal task must retain
at least one valid Pair. Retrieval, task-success, and efficiency claims then
apply their own preregistered Gates. A complete negative campaign remains a
completed Ship but exports no positive CV metric.

The deterministic reference runners always record
`production_evidence_complete=false`. Passing Stage A means the offline
reference path and evidence pipeline are internally consistent; it is not an
Agent benchmark result. Therefore Stage A cannot make any positive
task-effect or retrieval claim even if every scripted case passes.

## Paid authority and campaign boundary

The production adapter installs exact Pico and CodeCairn wheels into an
isolated Python 3.12 environment. Each task runs in a fresh installed worker
through the normal Pico Runtime. The Agent receives only `read_file`,
`write_file`, and bounded `exec`; the parent independently reruns the checker
and applies the sealed Verifier. Memory-off never constructs a CodeCairn
backend. Treatment retrieval uses CodeCairn's local FastEmbed profile, maps
installed Memory identities back to the frozen anonymous corpus, and records
ranked candidates separately from injected context.

Stage C binds the clean Pico commit, both wheel digests, installed distribution
identity, source-checkout isolation, and a credential-free local
remember/recall proof. The CodeCairn candidate remains immutable during
calibration and formal execution. Any CodeCairn repair starts a new campaign
identity.

The proposed calibration plus formal budget can be inspected without a
Provider call:

```bash
make picobench-codecairn-task-effect-estimate
```

Issue #59 and Issue #70 budgets were not reused. Issue #79 recorded
digest-bound authorization for the final Stage C inputs, exact Provider and
model, local retrieval profile, matrices, pricing source, a 25 CNY warning,
and a 30 CNY cumulative hard ceiling before the first live call. The campaign
charged 1.29966592 CNY and left zero open reservations. The failed calibration
blocked the formal matrix, so that authority is no longer active and no
additional paid call is part of this result.

Generated Trials, retrieval records, traces, Memory content, and rebuilt
reports remain under ignored evidence directories and outside Git. Updating
the product CodeCairn pin, package metadata, release workflow, or release
evidence remains a separate delivery.
