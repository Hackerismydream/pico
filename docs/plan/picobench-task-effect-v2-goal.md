# Codex Goal: build PicoBench task-effect v2

Status: Stage A accepted by GitHub Issue #77 for credential-free
implementation at CNY 0. Paid evaluation has not started and is not
authorized.

This Goal becomes executable only when the user invokes it in a separate
session. It does not inherit paid authority from Issue #59 or Issue #70. A new
GitHub issue and an explicit CNY hard ceiling are required before any live
Provider, embedding, reranking, or other paid external call.

## Objective

Build a checkout-only PicoBench task-effect v2 campaign that answers a harder
product question than the existing continuity tracer:

> When the same next task is solvable with or without long-term Memory, does
> CodeCairn improve verified task outcomes or reduce rediscovery cost without
> injecting irrelevant, stale, or cross-repository Memory?

The v2 campaign must turn repository facts and prior execution experience into
measurable next-task effects. It must preserve the existing PicoBench engine,
Pico Runtime, current CodeCairn continuity evidence, and historical task
identities.

The intended evidence chain is:

```text
prior repository work
  -> Pico Runtime and Tools
  -> CodeCairn durable capture
  -> process exit
  -> fresh next task
  -> Memory-off or CodeCairn variant
  -> normal repository inspection and Tool execution
  -> external deterministic Verifier
  -> task-level paired result
  -> retrieval, token, Tool, latency, and cost metrics
```

## Why v2 is necessary

The completed CodeCairn campaign is valid continuity evidence:

- 32/32 formal Trials reached terminal records;
- 16/16 Pairs were valid;
- CodeCairn passed 16/16 task Verifiers;
- Memory-off passed 0/16;
- the recorded Recall@5 value was 1.0;
- stale injection, cross-repository leakage, and Memory-off backend operations
  were zero;
- Positive Claim Eligibility failed because each hard-negative query returned
  three memories.

That result must remain unchanged and honestly labeled. It does not yet prove
general task uplift:

- all eight formal tasks use the same remember-a-random-value shape;
- the Memory-off arm has no repository path from which to rediscover the
  answer;
- the Agent can only call `joint_write_result`;
- one repeated hard-negative phrase supplies the negative retrieval evidence;
- the current Recall@5 numerator records whether any expected item appears,
  which is a Hit@5-style measure rather than item-level recall;
- the current irrelevant-injection value is a mean item count per query and
  may exceed 1, despite being named a rate.

PicoBench v2 does not delete or rewrite that campaign. It introduces a new
experiment identity for realistic task effect.

## Naming and version boundary

`PicoBench task-effect v2` is an evaluation-contract version. It is not:

- Pico package version `0.2`;
- a Pico product release;
- a CodeCairn distribution version;
- a Git tag;
- a replacement name for Pico Harness v0.2;
- permission to change `pyproject.toml`, `uv.lock`, or release workflows.

New schemas, Pack IDs, suite IDs, task IDs, experiment IDs, artifact roots, and
Claim Rules use a v2 identity. Existing v1 identities remain immutable.

Suggested identifiers are:

```text
schema: pico.picobench.codecairn-task-effect.v2
suite: codecairn-task-effect-v2
calibration Pack: codecairn-task-effect-calibration-v2
formal Pack: codecairn-task-effect-v2
retrieval suite: codecairn-retrieval-quality-v2
```

Do not reuse the existing `codecairn-memory-effect-v1` experiment identity.

## Planning base

This Goal was written from the following current state:

| Input | Planning value |
| --- | --- |
| Pico `origin/main` | `ae4ded389205dafb6a6ea78c3fcdb7feedd81eb7` |
| Existing CodeCairn formal experiment | `1c5496edfaa08212635f6218f9aaa55c3e942fcd1e79203a11a6b8c4d9b94623` |
| Current product CodeCairn pin | `e993eb562cf1bb0b89490de4e91c2a56d79eb3be` |
| Existing formal task schema | `pico.picobench.codecairn-memory-tasks.v1` |
| Existing formal matrix | 8 tasks x 2 variants x 2 repetitions |

Before implementation, fetch `origin/main`, compare it with this planning base,
and reconcile any changed PicoBench or CodeCairn contract. Do not silently
assume this snapshot remains current.

## Stage 0 execution authority

GitHub Issue [#77](https://github.com/Hackerismydream/pico-harness/issues/77)
owns this delivery. The Stage 0 audit confirmed that `origin/main` still
matched the planning base, the existing v1 experiment and product CodeCairn
pin were unchanged, and no v2 evaluation candidate had been frozen.

Issue #77 authorizes only the credential-free Stage A implementation at
CNY 0. Stage B and every live or billable action remain blocked until a later
explicit authority record. Issue #59 and Issue #70 budgets are not reusable.

## Authoritative context

Read these sources completely before editing:

1. `AGENTS.md`
2. `CONTEXT-MAP.md`
3. `CONTEXT.md`
4. `docs/INDEX.md`
5. `docs/plan/README.md`
6. `docs/evaluation/README.md`
7. `docs/evaluation/picobench-ship-1.md`
8. `docs/plan/analysis/picobench-ship-1.md`
9. `docs/plan/pico-codecairn-joint-evidence-goal.md`
10. `docs/specs/codecairn-memory-backend.md`
11. `benchmarks/README.md`
12. `benchmarks/picobench/README.md`
13. `benchmarks/picobench/tasks/codecairn_memory/formal.json`
14. `benchmarks/picobench/packs/codecairn_memory/`
15. `benchmarks/picobench/suites/codecairn_memory_effect.yaml`

The current code and retained artifacts own current facts. This Goal owns the
next campaign boundary, not historical result reinterpretation.

## Product questions

The v2 campaign answers four separate questions.

| Question | Evidence |
| --- | --- |
| Can CodeCairn retrieve relevant prior repository facts and experience? | labeled retrieval quality |
| Can it abstain when prior Memory is irrelevant, stale, or belongs to another repository? | negative, stale, conflict, and isolation cases |
| Does Memory improve next-task success under a fixed task budget? | task-level paired Verifier delta |
| If success is unchanged, does Memory reduce rediscovery effort? | paired tokens, repository reads, Tool calls, latency, and cost |

No single metric may substitute for all four questions. Continuity is a
prerequisite, not task-effect evidence.

## Ownership and dependency direction

| Concern | Owner |
| --- | --- |
| Runtime, Session, Context injection, Tool execution, Trial Host, Verifier, and paired evaluation | Pico |
| repository identity, Source Journal, import, Memory creation, retrieval, ranking, packing, and abstention | CodeCairn |
| Local Skills and BM25 | Pico |
| v2 task fixtures, labels, Claim Rules, Trial records, budget ledger, and report rebuild | PicoBench |
| an immutable CodeCairn candidate wheel and its own acceptance evidence | CodeCairn repository |
| promotion of a newer CodeCairn product pin | a separate Pico dependency delivery |

The dependency direction remains:

```text
benchmarks/picobench -> pico
pico -X-> benchmarks/picobench
```

PicoBench may use only the installed public CodeCairn Adapter and operator
surface. It must not import private CodeCairn storage, importer, retrieval, or
ranking modules.

## Release-safety boundary

The implementation remains checkout-only:

- `benchmarks/` stays excluded from the Pico wheel;
- `pico/` never imports PicoBench;
- package version remains unchanged;
- no `v*` tag is created;
- `.github/workflows/release.yml` is unchanged;
- the current CodeCairn dependency pin is unchanged;
- generated reports and raw Trial artifacts remain outside Git.

Merging checkout-only benchmark work changes the source commit but not the
intended wheel contents. Any commit-bound V-R0 or release evidence for an older
SHA must still be regenerated before a future release.

The v2 campaign may install a newer immutable CodeCairn wheel explicitly for
evaluation. If that wheel later deserves product promotion, update the
`pyproject.toml` and `uv.lock` pin in a separate `build` delivery after the v2
evidence is complete. Do not combine benchmark construction, task results,
and dependency promotion in one PR.

## Hard scope

The implementation may touch:

```text
benchmarks/picobench/
benchmarks/README.md
tests/test_picobench_codecairn_memory.py
tests/integration/test_picobench_codecairn_task_effect_e2e.py
docs/evaluation/
docs/plan/
docs/project-status.md
docs/feature-evidence.md
docs/roadmap.md
Makefile
```

Only touch result/status documents after a real campaign completes. During the
credential-free implementation delivery, describe contracts and commands, not
future results.

The implementation must not touch:

```text
pico/
pyproject.toml
uv.lock
.github/workflows/release.yml
RELEASING.md
```

If a product-side seam is genuinely required, stop and propose a separate,
minimal delivery with its own contract and tests. Do not use a benchmark need
to smuggle a Runtime refactor into this Goal.

## Non-goals

- Do not create a second benchmark engine, Runtime, Context Engine, Session
  model, artifact store, reducer framework, or budget ledger.
- Do not replace the existing v1 CodeCairn continuity Pack.
- Do not edit old task definitions after observing v2 results.
- Do not hide or delete negative Trials, timeouts, Provider failures, or
  infrastructure failures.
- Do not use an LLM judge as the final task Verifier.
- Do not benchmark model routing, crash recovery, Delivery exactly-once
  behavior, or external side-effect idempotency.
- Do not change CodeCairn code from the Pico repository.
- Do not add a local CodeCairn source dependency, monkey patch, copied private
  module, fallback backend, or dual write.
- Do not claim production SLO, general Coding Agent superiority, or release
  readiness from this campaign.

## Target architecture

Reuse the existing deep PicoBench module:

```text
frozen v2 task and retrieval definitions
  -> existing canonical Experiment Plan
  -> existing Comparison Blocks and Trial isolation
  -> installed Pico and CodeCairn pair
  -> real Runtime Assembly, Spine, Agent Loop, and repository Tools
  -> existing usage and budget recorders
  -> v2 external deterministic Verifiers
  -> v2 task-effect and retrieval reducers
  -> existing report rebuild
  -> v2 summary and claim-eligible CV export
```

The v2 Pack owns only task-specific schema, fixture construction, retrieval
labels, Verifier logic, metrics, and Claim Rules. Generic campaign execution,
retry, budget, terminal records, Pair coverage, and rebuild behavior remain in
the existing PicoBench engine.

## Track A: preserve the continuity tracer

The current v1 campaign remains a distinct continuity tracer:

```text
explicit fact in Session A
  -> CodeCairn store
  -> process exit
  -> fresh-process recall
  -> exact JSON output
```

Add regression coverage proving:

- old task, Pack, suite, schema, and experiment identities do not change;
- old reports still rebuild under their recorded schema;
- old `Recall@5` and irrelevant-injection field meanings remain historical and
  are not silently redefined;
- v2 reports never aggregate v1 Trials into v2 metrics.

If a historical metric name is ambiguous, document the old meaning and add a
new v2 field. Never rewrite retained evidence.

## Track B: retrieval-quality micro-suite

Create a separate retrieval suite outside the Agent Trial denominator.

### Formal corpus and queries

The formal suite contains at least 100 uniquely worded labeled queries:

| Class | Minimum count | Purpose |
| --- | ---: | --- |
| positive repository fact | 30 | retrieve facts still valid at the evaluated commit |
| positive execution experience | 20 | retrieve prior verified commands, failure lessons, or workflows |
| hard negative | 20 | abstain when similar vocabulary has no relevant Memory |
| stale or superseded | 15 | reject Memory invalidated by later repository state |
| cross-repository | 15 | prevent recall from another repository identity |

Calibration labels and formal labels must be disjoint. Avoid one repeated
negative phrase, one repository name pattern, or one synthetic token template.
At least ten positive queries must have more than one relevant Memory so true
item-level Recall@5 is exercised.

### Retrieval records

Each case records anonymous:

- query ID and class;
- expected Memory IDs;
- candidate and injected Memory IDs;
- rank, score, source, repository identity, and validity state;
- abstention decision and reason;
- stale or superseded status;
- retrieval latency;
- attributable embedding, semantic, and reranking usage and cost;
- terminal and failure class.

Memory contents remain outside aggregate reports.

### Metric definitions

Use unambiguous v2 metrics:

```text
positive_hit_at_5
  positive queries with at least one expected item in top 5
  / positive queries

positive_recall_at_5
  macro average of retrieved expected items in top 5
  / expected items for each positive query

positive_mrr
  macro mean reciprocal rank of the first expected item

injected_precision
  relevant injected items / all injected items on positive queries

hard_negative_any_injection_rate
  hard-negative queries with one or more injected items
  / hard-negative queries

mean_irrelevant_items_per_hard_negative
  irrelevant injected items / hard-negative queries

stale_any_injection_rate
  stale or superseded queries with any invalid injection
  / stale or superseded queries

cross_repository_any_injection_rate
  cross-repository queries with any foreign injection
  / cross-repository queries
```

Do not call a binary any-hit numerator item-level Recall@5. Do not call an
unbounded mean item count a rate.

## Track C: realistic next-task effect

### Formal task matrix

Use 24 formal tasks across at least four small, pinned repository fixtures:

| Class | Tasks | What Memory may improve |
| --- | ---: | --- |
| repository fact rediscovery | 8 | fewer searches and reads for stable conventions, paths, or commands |
| verified experience reuse | 8 | avoid a prior failed approach or reuse a verified repair workflow |
| stale or conflicting Memory | 4 | verify current state and avoid applying superseded guidance |
| irrelevant or no useful Memory | 4 | abstain and preserve baseline behavior |

Use at least six disjoint calibration tasks. Calibration and formal task IDs,
fixtures, expected outcomes, and Verifier data must not overlap.

The formal live matrix is:

```text
24 tasks
x 2 Memory variants
x 2 repetitions
= 96 planned Trials
```

Call them repetitions unless the Provider accepts and records a real seed.

### Task construction rules

Every task must satisfy all of these rules:

1. Both variants can solve the task from repository state and public Tools.
2. Memory-off is never required to guess an unobservable random value.
3. The next task is related to prior work but is not a verbatim recall quiz.
4. The Agent can inspect files, search text, run bounded commands or tests, and
   write the required artifact.
5. The treatment arm receives no extra Tool, token, iteration, timeout, retry,
   or expected-answer access.
6. The Verifier checks repository state, tests, output artifacts, path policy,
   and required receipts outside the Agent workspace.
7. Task success does not depend on the model asserting that it succeeded.
8. Each repository fixture is independently reset and digest-checked for every
   Trial.
9. Prior work produces a real Session-normalized CodeCairn capture rather than
   seeding a private database directly.
10. Stale and conflict tasks mutate repository state between the prior and
    evaluated task using a frozen parent-owned setup step.

The Tool surface should be the smallest realistic repository set, such as:

```text
read file
search repository
list paths
run bounded test or command
write or patch allowed files
submit final artifact
```

Do not grant web access. Use a fail-closed path policy and disposable
workspace. If the existing host cannot provide the required local Tool surface
without changing `pico/`, stop and redesign the Pack before requesting a
product seam.

### Variant discipline

The only Pair treatment axis is:

```text
control:   memory.backend = null
treatment: memory.backend = codecairn
```

Within each Pair, keep identical:

- Pico and CodeCairn wheel identities;
- model, Provider, endpoint class, and generation parameters;
- Context strategy and token budget;
- Local Skill corpus;
- Tool catalog and Tool implementations;
- workspace fixture and evaluated base commit;
- task prompt and prior-work sequence;
- timeout and iteration budget;
- Provider retry and Comparison Block retry;
- Verifier code and expected state.

Memory-off must record zero CodeCairn factory, lifecycle, capture, import,
recall, index, and external-call operations.

### Outcome metrics

Report at both run and task level:

- Verifier pass rate and paired pass delta;
- net gained and regressed tasks;
- main-Agent input and output tokens;
- Trial-total tokens including attributable auxiliary calls;
- repository read, search, test, write, and total Tool calls;
- exact repeated repository reads;
- end-to-end and retrieval latency;
- Provider and CodeCairn external-call cost;
- Memory hits, injected items, abstentions, and Memory-induced failures;
- all terminal and failure classes.

Cluster repetitions by `task_id`. Do not treat 48 Pairs as 48 independent task
definitions. Report a task-clustered bootstrap interval for paired task,
token, Tool, and latency effects.

## Calibration and task-validity Gate

Before the formal task set is frozen:

- a deterministic scripted policy proves both variants have a valid Tool path
  to every expected result;
- every Verifier detects at least one valid result and one representative
  incorrect result;
- task fixtures reset byte-identically;
- variant diff contains only `memory_backend`;
- Memory-off records zero CodeCairn operations;
- v1 report rebuild remains unchanged;
- the retrieval suite proves all metric denominators and class labels are
  non-empty.

Live calibration may detect Provider-contract, timeout, budget, fixture, or
Verifier defects. It must not be used to tune formal expected answers or
Positive Claim Eligibility thresholds.

Do not start the formal campaign if calibration shows the control arm is
structurally impossible on all tasks, every task is trivial for both arms, a
Verifier can be modified by the Agent, or task classes collapse to one
template. Repair the task Pack, change its digest, and rerun calibration.

## Claim model

Keep these states independent:

```text
ship_complete
measurement_valid
retrieval_claim_eligible
task_success_claim_eligible
efficiency_claim_eligible
```

A complete negative campaign is still a completed Ship. It exports no positive
CV metric.

### Ship completeness

Require:

- every planned Trial and Retrieval Case has one terminal record;
- every Comparison Block has a retained outcome;
- all failures and timeouts remain in their declared denominator;
- raw records rebuild `summary.json` without external calls;
- v1 and v2 records remain schema-separated.

### Measurement validity

Require:

- at least 44 of 48 formal Pairs are valid;
- every formal task has at least one valid Pair;
- every retrieval query class reaches its planned count;
- Pair ordering and retries follow the frozen plan;
- only the declared treatment axis differs;
- usage and cost are complete for every selected Trial;
- task and Verifier digests match the frozen plan;
- clustered statistics are present;
- no task, expected answer, Claim Rule, or denominator changed after formal
  execution began.

### Retrieval claim eligibility

Freeze the exact thresholds before live calibration. The initial target Gate
is:

```text
positive_hit_at_5 >= 0.80
positive_recall_at_5 >= 0.80
injected_precision >= 0.80
hard_negative_any_injection_rate <= 0.05
stale_any_injection_rate = 0
cross_repository_any_injection_rate = 0
memory_off_operation_calls = 0
```

Always report MRR, mean irrelevant items, latency, usage, and cost even when
they are not gating metrics.

### Task-success claim eligibility

Require all retrieval Gates plus:

- a positive task-level paired Verifier delta;
- at least three net gained formal tasks;
- no net regression in the stale/conflict or irrelevant/no-Memory classes;
- the task-clustered 95 percent bootstrap interval is reported;
- no task class is omitted from the aggregate.

The observed delta and interval may be reported descriptively. Do not claim
statistical significance unless the pre-registered test supports it.

### Efficiency claim eligibility

Efficiency is an alternative positive result when task success is non-inferior.
Require all retrieval Gates plus:

- treatment passes no fewer than one task below control across the 24-task
  formal set;
- no net regression in the stale/conflict or irrelevant/no-Memory classes;
- at least one pre-registered rediscovery metric improves by 15 percent or
  more: main-Agent input tokens, repository read/search calls, or repeated
  repository reads;
- Trial-total token, latency, and cost overhead are all reported;
- the task-clustered interval for the claimed metric is reported.

Do not hide auxiliary CodeCairn cost to make main-Agent efficiency look
better. Resume text must distinguish main-Agent token savings from Trial-total
cost.

## Staged execution

### Stage 0: authority and current-reality audit

Before code changes:

1. create or confirm one GitHub issue for PicoBench task-effect v2;
2. record the current Pico `main`, existing v1 experiment, product CodeCairn
   pin, and any candidate CodeCairn wheel;
3. authorize credential-free implementation at CNY 0;
4. record allowed paths, non-goals, task counts, Claim Rules, and stop
   conditions;
5. confirm that paid authority is not yet active.

### Stage A: credential-free implementation

Implement one reviewed Pico delivery:

1. versioned v2 task and retrieval schemas;
2. repository fixture builders and parent-owned Verifiers;
3. v2 Pack adapter over the existing campaign engine;
4. recording for true retrieval and injection metrics;
5. v2 reducer and Claim Rules;
6. deterministic task-validity and report-rebuild tests;
7. v1 identity and rebuild regression tests;
8. checkout-only smoke and Make targets;
9. contract and operator documentation.

Stage A must make zero paid external calls. Complete the normal commit,
self-review, PR, required checks, and squash-merge cycle before freezing a
formal campaign identity.

### Stage B: CodeCairn candidate handoff

Any abstention, relevance-threshold, stale-Memory, or repository-isolation fix
belongs to the CodeCairn repository.

The CodeCairn delivery may use only the v2 calibration subset for tuning and
must:

- avoid task IDs, repository names, or phrase-specific rules;
- preserve positive retrieval, stale handling, and repository isolation;
- produce an immutable commit, wheel, digest, and acceptance handoff;
- expose configuration through the public Adapter or operator contract;
- pass CodeCairn's own tests and benchmark Gates.

Pico consumes the resulting wheel as an immutable evaluation input. If no new
CodeCairn candidate exists, v2 may evaluate the current wheel and honestly
produce a negative result.

### Stage C: post-merge freeze and credential-free Gate

From the merged Pico `main` commit:

1. create a clean checkout;
2. build the Pico wheel;
3. acquire the exact CodeCairn wheel and handoff;
4. verify all wheel, handoff, task, fixture, Verifier, suite, and Claim Rule
   digests;
5. install the pair in an isolated Python 3.12 environment;
6. prove neither source checkout is importable by installed product code;
7. run continuity, repository isolation, Memory-off, fixture-reset, task-path,
   and report-rebuild Gates;
8. project worst-case Provider and external-service cost.

If Stage C fails, do not start calibration.

### Stage D: paid authority barrier

Before any live call, append a digest-bound authorization record to the new
issue. Freeze:

- Pico and CodeCairn commits, wheels, and handoffs;
- Provider, endpoint class, exact model, and fallback policy;
- embedding, semantic, retrieval, reranking, and abstention profiles;
- model parameters and seed capability;
- calibration and formal matrices;
- task, fixture, query-label, Verifier, Tool, suite, and Claim Rule digests;
- token, iteration, timeout, and retry limits;
- pricing source and all billable call classes;
- warning threshold, reserved maximum, and cumulative CNY hard ceiling.

Issue #59 and Issue #70 budgets are not reusable. Missing credentials, missing
authority, incomplete pricing, or projected worst-case cost above the new
ceiling is a hard stop.

### Stage E: live calibration

Run only calibration tasks and queries. Calibration may repair:

- Provider or Tool contract incompatibility;
- timeout or budget underestimation;
- fixture reset defects;
- Verifier defects;
- incomplete usage or cost records;
- mechanical report failures.

Any tracked repair changes the campaign digest and requires a reviewed Pico
fix, a new post-merge freeze, and renewed authorization. Do not change formal
task semantics, expected answers, or Claim Rules in response to treatment
performance.

### Stage F: formal campaign

After calibration passes, run:

```text
100 or more formal Retrieval Cases
96 formal E2E Trials
48 formal Pairs
```

Alternate or deterministically rotate variant order. Apply only symmetric,
pre-registered Provider and whole-Comparison-Block retries. Only a missing or
corrupt complete Pair may be rerun, and both variants must be rerun together.

Stop immediately when:

- cumulative reserved cost reaches the warning or hard-stop rule;
- a digest changes;
- a Verifier or task boundary is compromised;
- selected usage or cost is incomplete;
- Pair retries exceed the frozen limit;
- the installed pair no longer matches the approved handoff.

### Stage G: offline rebuild and claim reconciliation

After the campaign:

1. rebuild all reports from immutable records without Runtime or external
   calls;
2. emit `summary.json` with every result and failure;
3. emit `cv-metrics.json` with only eligible positive metrics;
4. update current status and evidence docs with exact commits, experiment ID,
   cost, and claim boundary;
5. leave raw Trials, Memory content, traces, and generated report assets
   outside Git;
6. decide CodeCairn product-pin promotion through a separate delivery.

## Artifact layout

Generated evidence remains ignored:

```text
.pico/evidence/picobench-codecairn-v2/<experiment-id>/
  plan.json
  approval.json
  pair-manifest.json
  deterministic/
    continuity.json
    task-validity.json
    fixture-reset.json
    v1-regression.json
  retrieval/
  trials/
  comparison-blocks/
  pairs/
  traces/
  workspaces/
  summary.json
  cv-metrics.json
  REPORT.md
```

`summary.json`, `cv-metrics.json`, and `REPORT.md` must rebuild from retained
records. Rebuild performs no Provider, Memory, embedding, reranking, Tool, or
MCP call and is byte-stable except for explicitly non-semantic fields.

## Verification

Stage A must run at least:

```bash
uv run pytest tests/test_picobench_codecairn_memory.py -x
uv run pytest tests/integration/test_picobench_codecairn_task_effect_e2e.py -x
uv run pytest tests/test_picobench_contract.py tests/test_picobench_reporting.py -x
make picobench-codecairn-task-effect-smoke
make check-large-files
```

Use the existing test files when they own the affected module. Do not add a
test filename with a ticket, phase, or version suffix.

Before merge:

- run `git diff --check`;
- prove no file above 1 MiB was added or modified;
- prove `pico/`, `pyproject.toml`, `uv.lock`, and release workflow are
  unchanged;
- build the distribution or inspect its canonical manifest to prove
  `benchmarks/` remains absent from wheel and sdist payloads;
- self-review the complete diff against this Goal and the authority issue.

The formal campaign runs only after the merged-main Stage C Gate and explicit
Stage D authority.

## Failure routing

| Finding | Action |
| --- | --- |
| existing PicoBench engine defect | fix PicoBench in the scoped Pico delivery and rerun Stage A |
| Pico Runtime or product seam required | stop and create a separate product contract and delivery |
| CodeCairn relevance, abstention, stale handling, or isolation defect | stop and fix CodeCairn in its repository |
| task, fixture, Verifier, metric, or reducer defect | invalidate the affected Pico campaign digest and restart from the repaired phase |
| Provider or external infrastructure failure | retain the terminal class and use only the symmetric frozen retry |
| task set is impossible for Memory-off or trivial for both variants | reject the Pack and redesign before formal execution |
| negative task or efficiency result | complete the Ship with the corresponding claim flag false |
| newer CodeCairn wheel passes v2 | evaluate product-pin promotion in a separate Pico delivery |

## Definition of done

This Goal is complete only when:

1. a dedicated issue owns the scope, Gates, immutable inputs, and paid
   authority;
2. v1 tasks, identities, reducers, and retained result meanings remain intact;
3. the v2 retrieval suite contains the planned positive, negative, stale, and
   cross-repository coverage with unambiguous metrics;
4. all 24 formal tasks are independently solvable without Memory and exercise
   realistic repository Tools;
5. the only paired treatment axis is `memory_backend`;
6. parent-owned deterministic Verifiers decide every task outcome;
7. Stage A is reviewed, merged, and rerun from the final `main` commit;
8. the installed Pico and CodeCairn pair passes the credential-free Stage C
   Gate;
9. no paid call occurs without a new digest-bound CNY authorization;
10. every planned Retrieval Case and Trial reaches a retained terminal record;
11. the offline rebuild reproduces the aggregate from raw evidence;
12. Ship Completeness, Measurement Validity, and all three claim-eligibility
    states are reported independently;
13. only eligible metrics enter `cv-metrics.json` or resume text;
14. generated evidence stays outside Git;
15. any CodeCairn product-pin update remains a separate reviewed delivery.

Do not stop after creating more tasks, passing deterministic tests, opening a
PR, or obtaining a perfect treatment score. The endpoint is an interpretable,
rebuildable comparison in which both variants have a real path to success and
negative results remain first-class.

## Next-session invocation

Use this branch and worktree:

```text
branch: feat/picobench_task_effect_v2
worktree: /Users/martinlos/code/pico-picobench-v2
```

The next session should begin with current-reality recovery, create or confirm
the authority issue, and execute only Stage A under CNY 0 unless the user
separately authorizes later paid stages.
