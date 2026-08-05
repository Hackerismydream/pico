# PicoBench Ship-1 contract

> **Status: Historical Ship-1 contract; the final-history task measurement is
> invalid.** Memory and Skill source names below are frozen experiment
> identity, not the current CodeCairn Runtime.
> The checkout-only harness, frozen suites, deterministic tracks, budget
> guard, calibration, formal campaign, and report rebuild completed. One
> Context Pair lacks complete usage evidence, and Tool disclosure regressed
> task pass count. No main-campaign metric is positive-claim eligible.

## Decision

Ship-1 will make five existing Pico capability areas measurable:

1. Runtime scheduling and full-path execution;
2. Context selection under long-session pressure;
3. cross-session Memory and Skill retrieval;
4. Tool disclosure over real MCP transport;
5. task-level Agent evaluation and reproducible reporting.

Task recovery remains Ship-2. The current Checkpoint is a filesystem safety net,
not a durable execution continuation protocol.

## Product question

Pico already contains Runtime, Context, Memory, Skill, Tool/MCP, and evidence
machinery. Ship-1 answers the missing product question:

> On frozen multi-turn tasks, which Pico mechanisms improve verified task
> outcomes, token efficiency, retrieval quality, and Tool selection, and by how
> much?

PicoBench is supporting evidence. Pico remains the Agent Harness and Runtime.

## Communication outcome

Ship-1 is designed so a reader can follow one problem-to-result chain without
knowing Pico's internal names:

| Agent application problem | Pico response | Ship-1 measurement |
| --- | --- | --- |
| Turn scheduling and execution can lose or blur request, cancellation, and failure semantics | Scheduler, Lane, AgentTurnRunner, Agent Loop, and typed outcomes form one Runtime path | R0 request-fate invariants plus R1 benchmark-host full-path deterministic Turns |
| Long Sessions crowd out early goals and decisions | budgeted Context segments with Curator-managed history, Working State, and fallback | verifier pass, Trial-total token delta, regressions, and latency versus FIFO |
| New Sessions repeat user understanding and successful task exploration | user Memory plus task-selected Local/EverOS Skills | retrieval quality, cross-session verifier delta, leakage, and source contribution |
| Large Tool catalogs inflate prompts and increase selection errors | one Tool contract, MCP integration, and progressive disclosure | estimated schema tokens, invalid/exact-repeat calls, verifier pass, and latency |
| Architecture changes are judged from demos or final text | frozen tasks, parent-owned Verifiers, paired reduction, and rebuildable artifacts | Pair coverage, task-level effects, failure breakdowns, and Claim Gates |

Implementation names remain available for interview follow-up; the first-level
project story is the application problem, the architectural response, and the
measured outcome.

## Resume-claim mapping

| Project claim | Required Ship-1 result | Boundary |
| --- | --- | --- |
| Runtime preserves request fate and full-path lifecycle semantics | R0 Scheduler invariants plus R1 benchmark-host full-path deterministic Turns | Ship-1 does not re-run or compare the CLI, TUI, Gateway, Channel, Cron, or Subagent adapters |
| Context controls long-session pressure | single-axis FIFO versus Curator task result and token comparison | Tool Schema savings are reported separately |
| Memory supports cross-session reuse | retrieval micro-suite plus user-Memory-off/on cross-process task comparison | the Skill source set remains identical |
| Skills select reusable experience | local-only versus Local-plus-EverOS retrieval and task comparison | the user-Memory segment remains identical |
| Tool/MCP scales to a larger catalog | real local MCP all-tools versus progressive-disclosure comparison | Schema tokens are estimated unless billed separately |
| Agent changes are measurable | frozen task set, deterministic Verifiers, paired statistics, rebuildable artifacts | negative result may be complete but not claim eligible |
| Tasks recover after process interruption | not earned by Ship-1 | requires Ship-2 attempt and side-effect protocols |

## External interface

The common caller uses:

```text
make picobench-smoke
make picobench
```

The Python interface is:

```python
async def run(spec: ExperimentSpec) -> ExperimentRef: ...

def rebuild_report(ref: ExperimentRef) -> ShipReport: ...
```

`run` validates, freezes, executes or resumes, verifies, records, and reduces.
`rebuild_report` performs no Provider, Memory, Tool, or MCP calls.

## Canonical data

### ExperimentSpec

The tracked Ship-1 specification contains:

```yaml
schema: pico.picobench.experiment.v1
suite: agent-application-ship-1
repetitions: 3
provider:
  name: ${PICO_BENCH_PROVIDER}
  model: ${PICO_BENCH_MODEL}
execution:
  timeout_seconds: 180
  retry_policy: symmetric
  provider_call_max_attempts: 2
  max_comparison_block_attempts: 2
  max_retrieval_query_block_attempts: 2
packs:
  runtime: runtime-v1
  context: context-v1
  memory_skill: memory-skill-v1
  tool_mcp: tool-mcp-v1
```

Secrets, absolute home paths, and access tokens never enter the specification
or experiment digest.

Capability thresholds use a typed, declarative `ClaimRule` schema owned by the
Experiment Plan. The thresholds in this contract are frozen before any
real-provider calibration or formal Trial. Pack adapters emit named metrics;
the generic reducer evaluates rules without hard-coding Pack behavior.

### Experiment identity

The experiment id is the SHA-256 digest of canonical JSON containing:

- Pico commit;
- suite, task, fixture, retrieval corpus, query-label, Verifier, variant, and
  retrieval-configuration digests;
- `uv.lock` digest;
- Provider and model identity;
- generation parameters;
- token and iteration budgets;
- Tool catalog digest;
- tokenizer identity, version, and vocabulary/config digest;
- effective Runtime configuration digest;
- executor/Sandbox mode;
- Python version, OS, and architecture;
- repetition count;
- timeout, Provider-call retry limit, Comparison Block attempt limit, and
  Retrieval Query Block attempt limit;
- evidence schema version.

The digest excludes:

- credentials;
- machine-specific absolute paths;
- generated timestamps;
- output directories.

The manifest also records actual Provider capability probes, pricing source,
seed support, and usage-field support. If cost cannot be bounded from the
approved model identity and plan budgets, the live campaign does not start.

Calibration uses task and query ids disjoint from the formal suite:

```text
64 E2E Trials
34 Retrieval Cases
```

Claim Rules are frozen before calibration. Calibration may repair only
mechanical harness, fixture, Verifier, or Provider-contract defects. Every
repair changes the digest and reruns calibration; observed effect size cannot
change a threshold or formal task.

### TrialKey

```text
experiment_id
pack_id
task_id
variant_id
repetition
```

### RetrievalCaseKey

```text
experiment_id
retrieval_suite_id
query_id
configuration_id
```

A Retrieval Case is not an Agent Trial. It owns one frozen labeled query under
one retrieval configuration and has its own immutable attempt records. A
`RetrievalQueryBlockKey` groups every configuration for the same suite and
query so Provider or infrastructure contamination reruns the complete query
block without mixing attempts.

Every terminal Retrieval Case Record contains:

- RetrievalCaseKey and all corpus, label, configuration, tokenizer, model, and
  environment digests;
- positive or hard-negative label and anonymous expected item ids;
- anonymous ranked backend results and final injected results;
- rank, score, source, contribution, and injection fields allowed by the
  suite schema;
- terminal status, immutable attempt references, findings, and usage;
- selected query-block attempt.

### ComparisonBlockKey

```text
experiment_id
pack_id
task_id
repetition
```

### AttemptKey

```text
ComparisonBlockKey
variant_id
block_attempt
```

`repetition` is the canonical term. It may be called a seed only when the
Provider accepts and records a real seed.

### PairKey

```text
experiment_id
pack_id
treatment_axis
task_id
repetition
control_variant_id
treatment_variant_id
```

A Trial may participate in more than one Pair. In the three-arm Memory/Skill
Pack, the Local-plus-EverOS treatment arm participates in both the Memory and
Skill comparisons. Every arm therefore runs inside one Comparison Block and
the reducer selects the earliest block attempt where all three arms are
measurable. Pair identity cannot be a scalar field in `TrialKey`.

### TrialRecord

Every planned Trial writes one terminal record containing:

- TrialKey, all identity digests, and its Pair memberships;
- declared variant settings and observed Runtime configuration fingerprint;
- start/end timestamps and timeout;
- Trial, Turn, delivery, and verification states;
- references to immutable attempt records and the selected block attempt;
- model-call usage and cost;
- Context path and fallback metadata;
- anonymous Memory/Skill selection records;
- Tool/MCP calls and failure categories;
- workspace and verifier digests;
- finding list;
- artifact references.

Each `PairResult` contains its PairKey and the actual pairwise variant diff.
That diff must contain exactly the Treatment Axis named by the PairKey.

## Variant discipline

Each Pair changes one treatment axis:

| Pack | Baseline | Treatment | Treatment axis |
| --- | --- | --- | --- |
| Context | FIFO-tail phase-B manager | current Curator phase-B manager | `history_manager` |
| Memory | user Memory recall disabled | user Memory recall enabled | `user_memory_recall` |
| Skill | local Skill source | local plus EverOS sources | `skill_sources` |
| Tool/MCP | all Tools visible | progressive Tool disclosure | `tool_disclosure` |

All other configuration must match:

- task and workspace fixture;
- model, Provider, generation parameters, and fallback;
- Context window and max output;
- Tool implementations and MCP catalog;
- timeout, iteration budget, and retries;
- Session history before the evaluated Turn;
- verifier and expected data.

A non-declared difference invalidates the Pair as
`infrastructure_failure: variant_drift`.

The Memory-off adapter keeps `MemorySegmentBuilder` enabled and suppresses only
delegated user-track backend recall, recording zero delegated calls. Host
`user.md` rendering, the real backend, Curator's Memory flag, and the Skill
source set remain identical. Passing `backend=None` is not a valid single-axis
Memory baseline because it also removes the EverOS Skill source and changes
Curator's Memory flag.

The three Task Packs use different controls. Their results may be summarized as
pack-specific single-axis measurements, but they are not a unified
`minimal_baseline` versus `pico_full` comparison. A product-wide delta requires
a separate preregistered campaign.

## Runtime tracks

### R0: Scheduler semantics

R0 exercises:

```text
Scheduler
  -> Lane
  -> OriginPools
  -> scripted TurnRunner
```

Default workload:

```text
2,000 accepted requests before drain
64 explicit post-drain rejection probes
64 conversations
16 USER slots
4 system slots
APPEND / INJECT / INTERRUPT / cancel / shutdown
```

Each request uses a unique `message_id`. Because an INJECT may merge into the
running Turn or fall back to APPEND, request count is not expected to equal
runner-invocation count.

Every accepted request enters exactly one request terminal state:

```text
executed
merged_into_running_turn
fallback_executed
cancelled_before_start
cancelled_while_running
```

A post-drain submission is recorded separately as `rejected_during_shutdown`
and must not receive a `TurnHandle`. Every submission, accepted or rejected, is
accounted for exactly once.

R0 records:

- accepted and rejected requests;
- request terminal-state counts;
- runner invocation identities;
- unresolved TurnHandles;
- pool concurrency;
- Lane queue depth;
- no-contention dispatch overhead;
- contention queue wait;
- runner execution latency;
- shutdown drain result.

R0 Gate:

```text
lost accepted request = 0
unexpected duplicate request execution = 0
unresolved TurnHandle = 0
pool limit violation = 0
lifecycle contradiction = 0
```

The report must not describe R0 as 2,000 real model requests.

### R1: full-path deterministic Runtime

Runtime Assembly first constructs the real Agent Loop, Session, backend, Tool,
MCP, and Sandbox dependencies. The Trial Host then wires the Runtime execution
path. R1 submits 100 deterministic requests across success, Tool-failure,
Provider-failure, and cancellation scenarios through:

```text
Scheduler
  -> AgentTurnRunner
  -> Agent Loop
  -> deterministic Provider
  -> deterministic Tool
  -> Session
  -> typed events / TurnOutcome
  -> DeliveryHub
  -> recording outlet
```

R1 proves that the benchmark host uses Pico's real composition rather than
testing only Scheduler data structures. Ninety-two submissions produce
readable Session and Delivery outcomes; the remaining injected Provider
failure and cancellation scenarios still retain Scheduler terminal evidence.
R1 does not independently prove every product Host adapter.

R1 Gate:

- every Turn enters Spine through `Scheduler.submit`;
- every runner is `AgentTurnRunner`;
- model and Tool events share the Turn identity;
- Session output is readable after Runtime teardown;
- delivered, injected-delivery-failure, and no-outlet cases have distinct
  outcomes after the DeliveryHub reaches idle;
- Turn terminal and delivery outcome are both present;
- expected Tool failures become
  `completed_with_tool_failure`, not clean completion;
- no Runtime or MCP resource remains open.

### Runtime latency vocabulary

```text
dispatch_overhead_ms:
  no-contention submit to runner entry

queue_wait_ms:
  contended submit to runner entry

execution_latency_ms:
  runner entry to runner return

end_to_end_latency_ms:
  submit to external Verifier terminal
```

Existing `TurnEnded.latency_ms` is execution latency. It must not be renamed
to scheduling overhead.

## Context Task Pack

### Task shape

Ship-1 tracks eight long-session tasks. Each task contains:

- 30 to 80 prior messages;
- an early constraint needed by the final task;
- at least one superseded constraint;
- long Tool Results;
- irrelevant noise;
- a deterministic final artifact;
- an external Verifier.

Example constraints include output timezone, forbidden paths, final filename,
required fields, and decisions made early in the Session.

### Single-axis comparison

Both variants use the same five Phase A segments and Tool definitions. The
declared treatment axis is the complete phase-B history manager:

```text
FIFO:
  FifoHistoryManager

Pico:
  CuratorSegmentBuilder
```

The current Curator owns selected history, optional Working State, archive
bookkeeping, and its `after_turn` hook. The FIFO baseline owns none of those
Curator behaviors. They are intentionally grouped into the single
`history_manager` axis; Ship-1 does not attribute the measured effect to
history selection alone.

The FIFO and full-history adapters exist only inside PicoBench. They do not
restore retired public Context Engine modes.

### Metrics

- verifier pass by task and repetition;
- main-Agent input tokens;
- Trial total tokens;
- early-constraint retention;
- Context fast/slow/fail-safe path;
- Context auxiliary-model tokens;
- end-to-end latency.

Positive Claim Eligibility for the eight-task Ship-1 pack requires:

- at least six of eight tasks each have at least two success-matched,
  usage-complete Pairs;
- for each covered task, compute baseline and treatment mean Trial-total input
  tokens over those repetitions, then compute
  `1 - treatment_mean / baseline_mean`;
- the equal-task macro average of those reductions is at least 15 percent;
- treatment pass count not below control pass count;
- at least six of eight tasks have a negative token delta;
- no task loses at least two of three verifier passes;
- all regressions and exploratory task-clustered confidence intervals reported.

The report also shows token results over all valid usage-complete Pairs.
Positive efficiency claims use success-matched coverage so early task failure
cannot manufacture a token reduction.

A two-percentage-point non-inferiority claim is not valid for eight tasks.

## Memory and Skill Task Pack

Memory and Skill share a task family but retain separate metrics and treatment
axes.

### User Memory retrieval micro-suite

The user-Memory corpus contains exactly 160 facts and 80 frozen queries:

```text
50 positive queries
30 hard-negative queries
one user_memory_on configuration
80 planned Retrieval Cases
```

The cases cover exact and paraphrased positives, stale or superseded facts,
and cross-workspace distractors. Each query executes through the enabled user
Memory recall and final Context-injection path. It is measured once under its
frozen corpus and configuration; failed infrastructure attempts are preserved
and the whole one-arm query block is retried.

The primary metric is
`memory.final_injection_recall_at_5`, macro-averaged across positive queries.
The report also keeps backend Recall@1/Recall@5, final-injection Precision@5,
and MRR@5. `memory.hard_negative_injection_rate` is:

```text
hard-negative queries that inject at least one irrelevant item
/
all hard-negative queries
```

Memory retrieval Positive Claim Eligibility requires:

```text
memory.final_injection_recall_at_5 >= 0.80
memory.hard_negative_injection_rate <= 0.05
memory.stale_injection_count = 0
memory.cross_workspace_leakage_count = 0
```

### Skill source-fusion micro-suite

The Skill corpus and query labels are separate from user Memory. It contains
Local BM25 and EverOS semantic candidates, reusable task experience,
hard-negative Skills, and source-overlap cases. It freezes:

```text
40 positive queries
20 hard-negative queries
3 configurations: local_only, everos_only, fused
180 planned Retrieval Cases
```

All three configurations for a query form one Retrieval Query Block. A
Provider or infrastructure failure reruns all three configurations under one
new query-block attempt; measured zero-recall results do not trigger rerun.

Skill metrics use their own namespace:

```text
skill.local_recall_at_5
skill.everos_recall_at_5
skill.fused_recall_at_5
skill.fused_mrr_at_5
skill.source_contribution
skill.hard_negative_injection_rate
skill.cross_workspace_leakage_count
```

A claim that weighted RRF improves retrieval requires:

```text
skill.fused_recall_at_5
  - max(skill.local_recall_at_5, skill.everos_recall_at_5)
  >= 0.05
skill.hard_negative_injection_rate <= 0.05
skill.cross_workspace_leakage_count = 0
```

Otherwise the report may state the fusion implementation and observed source
contribution, but not an improvement.

Both recording adapters store only:

```text
query_id
anonymous item id
source
rank
raw score
RRF score when applicable
contributing sources
injected
consuming Turn
```

They do not write recalled Memory or Skill content into the aggregate report.

Retrieval metrics macro-average over query ids, not configurations or
attempts. Positive retrieval claims require all 260 planned Retrieval Cases to
have measurable selected records, zero inconclusive cases, and a rebuild from
the immutable manifest plus stored evidence records. Provider and
infrastructure failures remain visible in first-attempt and all-attempt
denominators even when a later query-block attempt becomes measurable.

### End-to-end cross-session tasks

Every end-to-end Trial for the eight frozen tasks contains:

```text
learning Session
  -> Runtime teardown
  -> Memory backend quiescence
  -> fresh process
  -> evaluation Session
  -> deterministic Verifier
```

The Pack has three arms:

```text
user_memory_off:
  user Memory recall disabled
  Local plus EverOS Skill sources

user_memory_on_local_only:
  user Memory recall enabled
  Local Skill source only

user_memory_on_local_plus_everos:
  user Memory recall enabled
  Local plus EverOS Skill sources
```

Memory compares `user_memory_off` with
`user_memory_on_local_plus_everos`. Skill compares
`user_memory_on_local_only` with
`user_memory_on_local_plus_everos`. A user-Memory-off Trial must record zero
user-track recall calls; agent-track Skill recall remains available.
The suppressed baseline still renders the same host `user.md` Memory, keeps
Curator's Memory configuration enabled, and preserves both Skill sources. Only
delegated user-track recall is suppressed and counted.

End-to-end metrics:

- task-level verifier pass;
- token and latency;
- Tool calls;
- Memory hit and Skill injection identifiers;
- task-level paired delta.

The report may state the measured delta and confidence interval. It must not
claim broad generalization from eight tasks.

Memory positive task-result eligibility, calculated only from the Memory Pair,
requires:

- treatment gains at least two of 24 verifier passes;
- at least two tasks have a positive task-level delta;
- no task loses at least two of three verifier passes.

Skill positive task-result eligibility, calculated only from the Skill Pair,
uses the same task-level guardrails.
Retrieval and source-contribution measurements remain reportable even when the
task-result threshold is not met.

## Tool/MCP Task Pack

### Fixture

A deterministic local MCP server exposes 64 tools with intentionally similar
names, descriptions, and parameter shapes. This exceeds the current default
Tool Search compaction threshold of 50. Each of eight tasks needs one to three
specific Tools.

The final campaign must traverse a real supported MCP transport. Python-only
fake Tools prove contract behavior but do not earn an MCP result.

### Comparison

```text
all-tools:
  every Tool schema is visible

progressive-disclosure:
  core Tools plus tool_search / tool_call are visible
```

Both variants use the same underlying Tool implementations and MCP catalog.
The Trial Record proves that their initial model-visible Tool sets differ and
that `tool_search` / `tool_call` are connected in the treatment. Whether the
model actually invokes those meta-Tools is a measured product outcome. Failure
to invoke them is retained as task behavior, not filtered as variant drift.

A credential-free deterministic smoke separately proves:

```text
tool_search
  -> tool_call
  -> real local MCP transport
  -> expected receipt
```

### Metrics

- estimated visible Tool Schema tokens per main-Agent call and summed across
  the complete Trial;
- meta-Tool invocation and failure counts;
- first-target selection accuracy;
- unknown target calls;
- invalid target attempts;
- repeated target calls;
- normalized target-call count;
- Tool failure categories;
- verifier pass;
- latency.

The recorder normalizes both variants into `TargetCallRecord`:

```text
control direct catalog call
  -> one TargetCallRecord

treatment tool_call meta invocation
  -> unwrap name + arguments
  -> one TargetCallRecord

treatment direct hidden-catalog call
  -> one TargetCallRecord with route=direct_hidden

tool_search invocation
  -> meta-call record only
```

A malformed `tool_call` envelope still produces a TargetCallRecord with
`dispatch_status=invalid_envelope`; it cannot disappear before the invalid-call
denominator. A successfully unwrapped call records the nested target Registry
result and MCP receipt in addition to the outer meta-Tool event.

`first_target_accuracy` checks the first normalized TargetCallRecord against
the expected target. An exact target repeat uses this canonical key across the
complete Trial:

```text
target Tool name + canonical JSON target arguments
```

Malformed envelopes use a deterministic raw-argument fingerprint. The
`invalid_target_call_rate` denominator is every normalized TargetCallRecord and
counts invalid envelopes, unknown target names, and target Schema/argument
validation failures. `exact_target_repeat_rate` is repeated TargetCallRecords
divided by every normalized TargetCallRecord. Meta-Tool calls are excluded from
both denominators and reported separately. A zero-target denominator is null,
not zero; the task Verifier still requires the expected MCP receipt.

Tool/MCP Positive Claim Eligibility requires:

- at least six of eight tasks each have at least two success-matched,
  usage-complete Pairs;
- for each covered task, compute control and treatment mean Trial-total
  estimated visible Tool Schema tokens over those repetitions, then compute
  `1 - treatment_mean / control_mean`;
- the equal-task macro average of those reductions is at least 50 percent;
- at least six of eight tasks have lower treatment Schema-token totals;
- treatment pass count not below control pass count;
- invalid-target and exact-target-repeat direction not worse;
- no task loses at least two of three verifier passes;
- the initial model-visible Tool set differs in every treatment Trial;
- no silent MCP connection failure.

`invalid_target_call_rate` and `exact_target_repeat_rate` must be non-null for
every success-matched Pair used by the Claim Rule. A null rate makes the
positive Tool claim indeterminate rather than silently treating the value as
zero.

The result is an estimated schema-token reduction unless the Provider exposes
a separate billed Tool Schema field.

## Usage accounting

`trial_total_usage` includes every model call attributable to a Trial from the
first task Turn submission until required post-turn Memory persistence
quiesces, and ends before Verifier execution.

The Trial Record separates:

```text
call_role:
  main_agent
  context_auxiliary
  skill_auxiliary
  memory_auxiliary
  other

attempt_kind:
  initial
  retry
```

Every model call has a unique call id and is aggregated exactly once across the
orthogonal role and attempt dimensions. The report records input, output,
cache-read, cache-write, and reasoning tokens when the Provider supplies them.
Unknown fields remain null rather than zero.

Background Memory extraction or consolidation is awaited and counted when it
is required by a later Session in the same Task. Any other excluded auxiliary
call receives an incomplete-usage finding. A Trial with incomplete usage may
contribute task success but not token or cost claims. Context reporting always
includes both main-Agent input and Trial-total input/output so an auxiliary
Curator call cannot be hidden.

One Memory/Skill Trial covers both its learning Session and fresh-process
evaluation Session, including necessary post-turn work. If an external Memory
service performs model calls without exposing usage, its usage is marked
unknown and the report states the narrower Pico-Provider token boundary. A
Trial-total token or cost claim is ineligible when a required attributable
cost is unknown.

## Verification

Task success is determined from:

- files and structured data;
- Tool and MCP receipts;
- Session records;
- expected terminal events;
- path and digest constraints.

The model's final text is never sufficient evidence.

Each Verifier has positive and corruption contract tests. A Ship-1 campaign
does not start if a Verifier cannot:

1. accept a known-valid artifact;
2. reject a missing artifact;
3. reject an altered artifact;
4. reject a forbidden path mutation;
5. report its own infrastructure failure separately.

The Verifier and expected data live outside the disposable workspace and are
digest-checked before and after each Trial. Under direct host execution this is
tamper evidence, not an inaccessible security boundary.

## Pairing and statistics

Variant order inside a Comparison Block is derived from the experiment digest
and rotates across tasks. A Provider or infrastructure failure, missing
record, or corrupt record in any arm causes every arm in the Block to rerun
under one new block-attempt number. `task_failed` and `task_timeout` do not
trigger a rerun. They may be executed again only when another arm contaminates
the Block; the original result remains append-only. The reducer selects the
earliest block attempt at which every arm is measurable.

Provider-call retry occurs inside one arm attempt and is capped separately at
`provider_call_max_attempts = 2`. A Comparison Block has at most two total
block attempts, and a Retrieval Query Block has at most two total query-block
attempts. Exhausting either limit preserves the final contamination as a
terminal measurement-invalid result. All three limits are digest-bound and
included in the worst-case Provider call, token, and cost preflight.

A product-effect Pair is valid only when both sides are one of:

```text
passed
task_failed
task_timeout
```

If any arm has Provider or infrastructure contamination, no Pair derived from
that Block attempt is used.

Reports include:

- planned and valid Pair counts;
- planned, measurable, and failed Retrieval Case counts by suite and
  configuration;
- first-attempt end-to-end pass rate: first-attempt `passed` outcomes divided
  by all 216 planned base Trials;
- first-attempt Provider and infrastructure failure rates, each divided by all
  216 planned base Trials;
- all-attempt operational failure rate: Provider and infrastructure failure
  Attempt Records divided by all stored Attempt Records;
- product pass rate: selected `passed` outcomes divided by selected
  `passed`, `task_failed`, and `task_timeout` outcomes;
- task-level pass rate;
- paired task delta;
- task-clustered bootstrap 95-percent confidence interval;
- Provider and infrastructure failure rate;
- timeout and inconclusive counts.

Repetitions of one task are correlated. For each task, the reducer first
averages the valid repetition deltas. It then performs 10,000 bootstrap samples
over task ids, with the random seed derived from and saved in the Experiment
Plan.

Each single-axis comparison requires at least 22 of 24 valid Pairs and at least
two valid Pairs for every task before publishing a product delta. Eight-task
confidence intervals are exploratory. Invalid Pairs and all failed attempts
remain visible in the report.

The formal campaign requires `inconclusive_count = 0`. An inconclusive result
indicates a broken task/evidence contract and cannot be hidden by the Pair
coverage allowance.

The aggregate across Context, Memory, Skill, and Tool uses pack-specific
controls and is labeled a stratified pack-specific-control summary. It must not
be described as one Pico-full overall lift.

Retrieval Cases use separate denominators:

```text
first-attempt retrieval operational failure rate
  = Provider/infrastructure first attempts / 260 planned Retrieval Cases

all-attempt retrieval operational failure rate
  = Provider/infrastructure attempts / all stored Retrieval Case attempts

retrieval measurement coverage
  = measurable selected Retrieval Case Records / 260 planned Retrieval Cases
```

Relevance metrics macro-average the selected measurable record for each query.
No retrieval result is added to the 216 E2E Trial or 120 Pair denominator.

## Artifact contract

```text
.pico/evidence/picobench/<experiment-id>/
  manifest.json
  journal.jsonl
  trials/
    <pack>/<task>/<repetition>/<variant>/
      trial-record.json
      attempts/
        <block-attempt>/
          attempt-record.json
          verifier.json
          usage.json
          selection.json
          trace-index.json
          workspace-digest.json
  blocks/
    <pack>/<task>/<repetition>/
      block-result.json
  pairs/
    <pack>/<treatment-axis>/<task>/<repetition>/
      pair-result.json
  retrieval/
    <suite>/<query>/<configuration>/
      retrieval-case-record.json
      attempts/
        <query-block-attempt>/
          retrieval-attempt-record.json
          selection.json
          usage.json
    query-blocks/
      <suite>/<query>/
        retrieval-query-block-result.json
  summary.json
  cv-metrics.json
  REPORT.md
```

An Attempt Record is complete only when it is parseable, terminal, and
digest-matched. A Trial is resumable only when a parseable BlockResult selects
one block attempt for every arm, or the symmetric block retry budget is
exhausted and the final contamination is explicitly retained. A lone Provider
or infrastructure failure never makes the rest of its Block skippable. Trial
summary writes use atomic replacement; Attempt and journal records are
append-only.

A Retrieval Case is complete only when its terminal summary selects a
digest-matched attempt or records exhausted symmetric query-block retries.
Retrieval Case summaries use atomic replacement; their attempt and journal
records are append-only.

`summary.json` contains the complete result. `cv-metrics.json` contains only
positive-claim-eligible measurements. The formal Ship-1 output is:

```json
{
  "experiment_id": "abffb7d2fe6a76f1102741cacd3cff1ed02697be0fb37fe2fa7a910dbeb11b4d",
  "ship_complete": true,
  "measurement_valid": false,
  "positive_claim_eligible": false,
  "eligible_metrics": {}
}
```

The complete eligibility decision, including negative results and reasons,
lives in `summary.json`; an ineligible capability is absent from
`cv-metrics.json`.

Generated reports and raw Trial artifacts remain outside Git.

## Formal result snapshot

The final-history formal campaign ran from clean source commit
`e6c790e37d707f74c44896dbcba9de9ee4ad8327` using
`deepseek / deepseek-v4-flash`. It recorded three repetitions because the
Provider did not expose a seed.

The R0 and R1 rows are a separate credential-free measurement bound to clean
source commit `e6c790e37d707f74c44896dbcba9de9ee4ad8327`. Its immutable Runtime
evidence digest is
`1c9fc1c4882ff09e3cf44140d84206bfb5ce923344cf7e482615a36e4f0f6006`.

| Scope | Formal result | Claim boundary |
| --- | --- | --- |
| R0 Runtime | 2,000 accepted requests; 0 lost; 0 unexpected duplicate executions; 0 unresolved handles; P95 dispatch overhead 0.761958 ms; P95 queue wait 190.124417 ms | Deterministic Scheduler semantics, not live LLM throughput or a production SLO |
| R1 Runtime | 100 Scheduler submissions exercised success, Tool-failure, Provider-failure, and cancellation scenarios; 92 produced readable Session and Delivery outcomes | Deterministic composition coverage |
| Context | 23/24 valid Pairs; one comparison exhausted its symmetric retry without complete treatment usage evidence | Measurement invalid; no Context token-efficiency claim |
| Semantic Memory E2E | 24 valid Pairs; Memory-off 0/24 passed; Memory-on 0/24 passed | Valid negative result; no task-effect claim |
| Memory Retrieval | 80/80 measurable; fixture Recall@5 1.0; no irrelevant, stale, or cross-workspace injection | Deterministic fixture contract only; not a semantic EverOS claim |
| Skill E2E | 24 valid Pairs; three net gains across three positive tasks | Real semantic task-effect evidence is absent; no task-effect claim |
| Skill fusion | 180/180 measurable; fixture fused Recall@5 1.0 versus 0.625 per single source | Deterministic fixture contract only; not a semantic retrieval claim |
| Tool/MCP | treatment 20/24 passed versus control 23/24; 93.4513% equal-task macro estimated visible Schema-token reduction across six measurable tasks | Measurement valid but positive-claim ineligible because task success regressed; real local stdio MCP transport |
| Campaign integrity | 216/216 terminal E2E Trials; 260/260 measurable Retrieval Cases; 119/120 valid Pairs; stable report digest | Ship complete but measurement invalid |

Selected Trial outcomes are 82 passed, 72 task failures, 61 task timeouts, and
one infrastructure failure. Rebuilding the report from raw artifacts produced
digest
`25ca985d2f80560fba789d14fc76acc07d0a45ea3b6a0b4aa7a3d4cfadf19eb1`.

The cumulative main-campaign ledger recorded a 25.26335175 CNY Provider
high-water mark. Adding the fixed 5 CNY external-service reserve yields
30.26335175 CNY committed against the cumulative 100 CNY hard cap. These are
budget-control estimates rather than Provider invoice amounts.

## Ship Gates

### G0: authority and identity

- an accepted GitHub issue owns the implementation scope;
- the final campaign runs on a clean commit or clean worktree;
- source, task, fixture, retrieval corpus, query-label, variant,
  retrieval-configuration, Verifier, lockfile, tokenizer, effective Runtime
  config, executor, and environment digests match;
- Provider and actual model identity, capability probe, and approved cost
  ceiling are recorded;
- planned maximum calls, tokens, and estimated cost fit under that ceiling
  before a paid Trial starts, including Provider-call and block-attempt upper
  bounds;
- credentials are absent from artifacts.

### G1: harness and Verifier integrity

- the smoke plan can run, resume, and rebuild;
- corrupted Trial Records are rejected;
- Verifier positive and corruption tests pass;
- a changed Verifier digest is an infrastructure failure;
- report rebuild is semantically byte-stable after normalizing generated time.
- `pico/` never imports `benchmarks.picobench`, and PicoBench is absent from
  the wheel manifest.

### G2: Runtime

- R0 accepted requests each enter one terminal request state;
- lost request, unexpected duplicate execution, unresolved handle, and pool
  violation are zero;
- R1 submits exactly 100 requests through Scheduler and `AgentTurnRunner`; 92
  produce readable Session and Delivery outcomes while injected Provider
  failure and cancellation scenarios retain Scheduler terminal evidence.

### G3: paired experiment completeness

- every planned Trial has a terminal Trial Record;
- every one of the 260 planned Retrieval Cases has a terminal Retrieval Case
  Record;
- 216 counts planned base Trials; extra block attempts are reported separately
  and never inflate the planned denominator;
- 260 counts planned Retrieval Cases; extra query-block attempts are reported
  separately and never inflate that denominator;
- all failures and timeouts remain in the report;
- retry and Comparison Block rerun rules are symmetric;
- each single-axis comparison has at least 22 of 24 valid Pairs;
- every task has at least two of three valid Pairs;
- inconclusive count is zero;
- variant drift is zero.

### G4: capability integrity

- user-Memory-off delegated user-track recall call count is zero while host
  Memory, Curator configuration, and declared Skill sources remain identical;
- Memory and Skill selections are anonymously traceable;
- all 260 Retrieval Cases are measurable before a positive retrieval claim;
- cross-workspace leakage is zero;
- Tool/MCP tasks traverse real local MCP transport;
- Tool-disclosure treatment starts with the declared compact model-visible
  Tool set, the same underlying MCP catalog, and connected meta-Tools;
- deterministic smoke proves the Tool Search to Tool Call to MCP receipt path;
- usage is complete for every token or cost claim.

### G5: Measurement Validity and Positive Claim Eligibility

G0 through G4 prove experiment completeness. Each capability separately
applies its claim threshold. A negative or uncertain result may have:

```text
ship_complete = true
measurement_valid = true
positive_claim_eligible = false
```

An experiment with invalid treatment isolation or inadequate Pair coverage has
`measurement_valid = false` regardless of whether its observed number looks
positive. `positive_claim_eligible = true` requires both
`ship_complete = true` and `measurement_valid = true`.

### G6: report rebuild

- report generation reads only the immutable manifest and stored Attempt,
  Trial, Comparison Block, Pair, and Retrieval Case records;
- report generation performs no Runtime, Provider, Memory, Tool, or MCP calls;
- all aggregate numbers trace to task, variant, repetition, and Verifier;
- repeated rebuilds preserve semantic content and digest;
- the report commit matches the experiment manifest.

## Ship-1 exit condition

Ship-1 is complete when:

```text
R0: 2,000 Scheduler requests
R1: 100 Scheduler submissions, 92 readable Session/Delivery outcomes
Context: 8 tasks x 2 variants x 3 repetitions
Memory/Skill: retrieval micro-suite plus 8 tasks x 3 variants x 3 repetitions
Semantic Memory effect: 8 tasks x 2 variants x 3 repetitions
Tool/MCP: 8 tasks x 2 variants x 3 repetitions
Total: 216 planned real-provider Trials
Comparison Blocks: 96 across four Task Packs
Pairs: 120 matched single-axis Pairs across five comparisons
Retrieval: 260 planned Cases across 140 query blocks
```

G0 through G4 and G6 close the campaign and evidence lifecycle. G5 records the
measurement-validity and positive-claim verdict even when that verdict is
false.

Ship-1 does not guarantee a positive result. Resume improvement claims may use
only values present in `cv-metrics.json`. Deterministic Runtime invariants and
latency measurements may also be quoted from the immutable Runtime evidence
artifact when `claim_eligible=true` and the evidence is explicitly labelled as
R0 Scheduler or R1 full-path deterministic evidence. They are not live
throughput, task-effect, or production SLO claims.

Ship-1 does not produce one `pico_full` versus `minimal_baseline` product
delta. If that claim later becomes necessary, it requires a separate 24-task,
two-variant, three-repetition campaign with its own plan and 144 additional
Trials.

## Deferred to Ship-2

Ship-2 owns:

- durable attempt journal in the Runtime;
- incomplete-attempt detection after process death;
- turn-level recovery protocol;
- fault injection at model, Tool, state, and delivery phases;
- idempotency keys and side-effect receipts;
- external delivery outbox and compensation;
- recovery and duplicate-side-effect metrics.

Ship-1 Trial-level resume skips a resolved Comparison Block or reruns every arm
of the unresolved Block under one new block-attempt number. It is not mid-Turn
recovery and must never be described as such.

## Required tests

Implementation tasks must add:

- schema and digest contract tests;
- Retrieval Case, Retrieval Query Block, and query-level rebuild tests;
- atomic Trial Record and crash-tail tests;
- Comparison-Block-aware Trial resume tests;
- variant-drift rejection tests;
- positive and corruption tests for every Verifier;
- R0 lifecycle invariant tests;
- R1 full-path deterministic integration;
- Context single-axis tests;
- Memory-off zero-call and cross-state-isolation tests;
- real local MCP transport integration;
- usage aggregation completeness tests;
- clustered-reducer golden tests;
- report rebuild stability tests.
