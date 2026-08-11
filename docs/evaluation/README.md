# Agent application evaluation

> **Status: Implemented checkout-only evaluation scope.** GitHub Issue
> [#59](https://github.com/Hackerismydream/pico-harness/issues/59) owns
> PicoBench Ship-1. Implementation does not imply a positive result: generated
> campaign evidence remains outside Git and owns every measured claim.

This scope defines how Pico measures whether its Runtime, Context, Memory,
Skill, and Tool/MCP behavior improves multi-turn Agent tasks. The evaluation
track consumes the shipped Runtime; it is not a second Agent Runtime and is not
an end-user product surface.

The deterministic
[Runtime scheduler experiments](runtime-scheduler-experiments.md) separately
compare session-level scheduling and USER/Runtime-origin concurrency isolation,
then repeat the accepted-request fate conformance track. Their local queueing
metrics are architecture evidence, not a production service-level objective.

The historical
[semantic retrieval addendum](picobench-semantic-addendum.md) separately
measured the former production EverOS Memory and Skill retrieval path. It does
not overwrite the frozen Ship-1 campaign or become CodeCairn evidence.

The former CodeCairn joint Memory and task-effect v2 tracks are archived.
Their executable Packs, campaign runners, frozen task inputs, and active test
surface have been removed from this checkout. The dated results remain in
[the task-effect v2 record](picobench-task-effect-v2.md), the completed Goal
documents, Issues #70 and #79, and their commit-bound external artifacts. They
are historical evidence only and are never relabeled as Myna evidence.

The current [Myna task-effect v1](picobench-myna-task-effect-v1.md) track is a
separate installed-candidate experiment. It uses the public Myna
`MemoryBackend`, crosses a real process and Session boundary, and measures
verified task parity plus repository rediscovery effort. Its deterministic Agent
policy is frozen-workload evidence, not general-purpose model uplift.

## Purpose and boundary

PicoBench owns the repeatable experiment lifecycle:

```text
frozen tasks
  -> canonical experiment plan
  -> isolated trials
  -> real Pico Runtime
  -> external deterministic verification
  -> paired reduction
  -> rebuildable report
```

It delegates Agent behavior to the existing Runtime and delegates final product
release readiness to V-R0.

| PicoBench owns | PicoBench delegates |
| --- | --- |
| Task and variant schemas | Turn execution to Runtime Assembly and Spine |
| Trial planning and isolation | Model calls to the configured Provider |
| Comparison-Block-aware Trial resume | Context construction to the selected Context Engine adapter |
| Artifact and failure classification | Memory storage and recall to `MemoryBackend` |
| External deterministic Verifiers | Skill selection to SkillForge |
| Paired statistics and report rebuild | Tool execution and MCP transport to the Tool system |
| Positive Claim Eligibility | Product release readiness to V-R0 |

PicoBench does not own:

- Agent Loop orchestration;
- a public `pico bench` command;
- mid-Turn continuation or crash recovery;
- a durable external-side-effect outbox;
- model routing evaluation in Ship-1;
- Evolver candidate evaluation;
- release versioning, tagging, or publication.

## Relationship to the Runtime

Composition and Turn execution are separate views. Runtime Assembly owns
construction and teardown; it is not a stage that every Turn traverses.

### Composition

```text
Experiment Plan
  -> PicoBench Trial Host
  -> assemble_runtime(...)
  -> RuntimeAssembly
       -> AgentLoop
       -> SessionManager
       -> MemoryBackend
       -> owned MCP and Sandbox lifecycle
  -> AgentTurnRunner / Scheduler / DeliveryHub
```

### Turn execution

```text
Scheduler.submit
  -> Lane / OriginPools
  -> AgentTurnRunner.run
  -> AgentLoop.run_turn
  -> Context / Memory / Skill / Tool / MCP
  -> RunnerEvents / TurnOutcome
  -> event sink / DeliveryHub
```

The dependency direction remains:

```text
benchmarks/picobench -> pico
pico -X-> benchmarks/picobench
```

The dependency direction follows the existing independent-evaluation rule:
`benchmarks/` may import `pico/`; `pico/` must never import `benchmarks/`.

## Canonical concepts

The Runtime glossary in [`CONTEXT.md`](../../CONTEXT.md) owns the canonical
definitions. This section records their relationships inside this scope.

| Term | Meaning |
| --- | --- |
| PicoBench | The checkout-only Agent application evaluation harness |
| Experiment Plan | Immutable identity of one task set, variant matrix, Runtime commit, model configuration, and evidence contract |
| Task Pack | A narrow task family with one schema, one Verifier family, and a fixed variant matrix; each derived Pair owns one treatment axis |
| Trial | One task, one variant, and one repetition executed in an isolated state root |
| Retrieval Case | One labeled retrieval query under one retrieval configuration, recorded outside the Agent Trial matrix |
| Comparison Block | Every variant for one Pack task and repetition, rerun together under one block-attempt number |
| Pair | Baseline and treatment Trials with the same task, repetition, model, budget, and fixture |
| Trial Record | The digest-bound terminal summary for one planned Trial; immutable attempt records remain append-only |
| Deterministic Verifier | Parent-owned code that decides task success from artifacts rather than model self-report |
| Ship completeness | Whether every planned Trial and Retrieval Case plus all integrity Gates completed |
| Measurement validity | Whether treatment isolation, Pair coverage, failure retention, and statistics make the result interpretable |
| Positive Claim Eligibility | Whether a valid measured result crosses its preregistered threshold and may be used as a positive project claim |

A Trial may contain multiple Turns. A Trial is not a synonym for a Turn or an
Evolution Run.

## Modules and interfaces

PicoBench is a deep checkout-only module. Its external interface remains small:

```python
async def run(spec: ExperimentSpec) -> ExperimentRef: ...

def rebuild_report(ref: ExperimentRef) -> ShipReport: ...
```

The default operator adapters are:

```text
make picobench-smoke
make picobench
make picobench-reproduce
make picobench-myna-task-effect-plan
make picobench-myna-task-effect-run
make picobench-myna-task-effect-verify
```

`make picobench-smoke` is credential-free and validates the contract,
deterministic Tracks, local MCP transport, and report rebuild.
`make picobench` performs the live Provider preflight and executes or resumes
the frozen Ship-1 plan. Re-running a complete plan performs no model calls and
rebuilds the report from the immutable manifest and stored evidence records.
`make picobench-reproduce` is the current multidimensional Scorecard operator
entry point. It runs or reuses the independent Runtime, TokenWise, CodeCairn
Memory, Context, and Tool/MCP evidence tracks, then emits one terminal summary
and one digest-bound local report directory. It requires explicit paid execution
consent whenever any paid track is missing.
`make picobench-myna-task-effect-plan` freezes the exact installed candidate,
task matrix, order seed, and evidence contract without running a Trial. The run
target executes or resumes the credential-free deterministic Agent A/B; the
verify target reinstalls the same wheels and rebuilds the evidence. No paid
Provider is involved, although the first local FastEmbed prefetch may download
its pinned model.

The implementation hides:

- plan validation and canonical digests;
- task-by-variant expansion;
- deterministic pair ordering;
- workspace, Session, EverOS, trace, and usage isolation;
- Provider and MCP lifecycle;
- Trial-level timeout and resume;
- artifact normalization;
- Verifier execution;
- result classification;
- task-clustered paired statistics;
- Measurement Validity and Positive Claim Eligibility;
- report rendering and rebuild checks.

Its internal modules keep these responsibilities local:

| Module | Interface responsibility |
| --- | --- |
| Plan Compiler | Validate the suite and produce a canonical Trial matrix |
| R0 Scheduler Track | Exercise request fate and concurrency semantics through a scripted `TurnRunner` |
| R1 Full-runtime Trial Host | Boot the real composition and execute Trials through Spine |
| Trial Recorder | Persist immutable Attempt Records and one digest-bound terminal Trial summary |
| Retrieval Recorder | Persist query-level ranked results, injection decisions, failures, and immutable attempts |
| External Verifier | Decide task success from parent-owned artifacts |
| Pair Reducer | Select valid Pairs and calculate task-level effects |
| Report Rebuilder | Reconstruct every aggregate without Runtime or Provider calls |

## Internal seams and adapters

Only behavior that has at least two real implementations receives a seam.

| Seam | Adapters required by Ship-1 |
| --- | --- |
| Turn execution | scripted `TurnRunner`; real `AgentTurnRunner` |
| Provider | deterministic Provider; configured real Provider |
| phase-B history manager | FIFO-tail manager; full-history manager; current Curator manager |
| user Memory recall | delegated user-track recall suppressed; delegated recall enabled, with the same Memory segment and backend |
| Skill source set | historical Ship-1: local-only or Local plus EverOS; CodeCairn joint track: the same fixed Local corpus in both arms |
| Tool disclosure | all Tools; progressive Tool disclosure |
| MCP | real local transport fixture; test fake used only by contract tests |
| Deterministic Verifier | file/JSON state; Tool-receipt sequence; Runtime-event contract |

Task Packs own their local task schemas. PicoBench must not expose a generic
workflow or DAG language that duplicates Runtime orchestration. The filesystem
is the only production artifact store in Ship-1; an in-memory test helper does
not justify another storage port.

## Lifecycle and state ownership

```text
precheck
  -> freeze plan
  -> compile Trial matrix
  -> run deterministic tracks
  -> run real paired tracks
  -> verify each Trial
  -> atomically record each terminal Trial
  -> reduce complete Pairs
  -> render and rebuild-check reports
```

PicoBench writes raw evidence under:

```text
.pico/evidence/picobench/<experiment-id>/
```

The repository tracks schemas, task definitions, Verifiers, fixtures, and
rerun commands. It does not track raw model transcripts, live Memory content,
generated reports, or other report assets.

Each Trial owns separate:

- workspace;
- `PICO_HOME`;
- backend state root (historical EverOS or the current CodeCairn joint track);
- Session identity;
- trace identity;
- Tool/MCP process lifecycle;
- artifact directory.

## Result state

Task success, Runtime terminal state, delivery outcome, and experiment
infrastructure state are separate dimensions.

```text
trial status:
  passed
  task_failed
  task_timeout
  provider_failure
  infrastructure_failure
  cancelled
  inconclusive

turn terminal:
  completed
  completed_with_tool_failure
  provider_failed
  error
  cancelled

delivery outcome:
  delivered
  dropped
  no_outlet

verification:
  passed
  failed
  not_run
```

No Boolean may collapse these vocabularies. Provider or infrastructure failure
is never a product pass, and a completed Turn is not automatically a passed
task.

A missing expected artifact is `task_failed`. A healthy Agent exhausting its
task budget is `task_timeout`. Provider transport failure is
`provider_failure`; a broken fixture, Verifier, plan, or artifact writer is
`infrastructure_failure`. `inconclusive` is reserved for contradictory evidence
and is a campaign-blocking contract defect, not a fallback bucket.

## Evidence and threat boundary

The Ship-1 threat model is a local, cooperative evaluation operator. A
Verifier and its expected data:

- run in the parent harness after the Agent Trial exits;
- are not placed in the disposable workspace;
- are not included in prompts or Tool definitions;
- are hashed before and after the Trial;
- fail the Trial as an infrastructure error if their digest changes.

Host execution does not make an external file inaccessible. When a final
campaign requires adversarial isolation, the Trial must use BoxLite or another
explicit fail-closed Sandbox. Ship-1 documents tamper evidence; it must not
claim a security boundary that direct host execution does not provide.

## Scope-wide constraints

- A Pair differs on exactly one declared treatment axis.
- variant order inside a Comparison Block is deterministic from the plan
  digest and rotates to reduce Provider time drift.
- Provider-call retry and experiment-block retry are separate frozen limits.
  Provider or infrastructure contamination, missing records, or corrupt
  records cause every variant in the Comparison Block to be rerun under one
  new block-attempt number, up to the plan limit.
- Retrieval Cases use their own frozen query/configuration identity and
  query-block retry rule; they never inflate the 216 E2E Trial denominator.
- Every planned Trial has a terminal Trial Record.
- Timeouts and failures remain in the denominator and raw report.
- LLM judges may add diagnostics but cannot determine task success.
- user-Memory-off must prove zero user-track recall calls while preserving the
  declared Skill source set.
- MCP claims require a real local MCP transport.
- Tool Schema token counts are tokenizer estimates unless the Provider reports
  a billed schema field.
- Usage covers every model call attributable to the Trial, not only the final
  Agent Loop call.
- Report rebuild reads only the immutable manifest and stored Attempt, Trial,
  Comparison Block, Pair, and Retrieval Case records. It performs no Runtime,
  Provider, Memory, Tool, or MCP calls.
- `ship_complete`, `measurement_valid`, and `positive_claim_eligible` are
  recorded separately; positive eligibility implies the first two.
- Negative results may complete Ship-1; they do not earn a positive claim.

## Documents

| Document | Purpose |
| --- | --- |
| [TokenWise cost experiment](tokenwise-cost.md) | Four-arm cache-policy experiment, workload matrix, metric formulas, and positive-claim gates |
| [PicoBench Ship-1 contract](picobench-ship-1.md) | Task packs, variants, metrics, statistics, artifacts, and Gates |
| [Ship-1 delivery analysis](../plan/analysis/picobench-ship-1.md) | Module decomposition, integration enumeration, dependency graph, and task split |
| [Delivery tasks](../plan/tasks/) | Smallest independently verifiable implementation slices |
