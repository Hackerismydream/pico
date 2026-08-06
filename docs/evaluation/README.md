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

The CodeCairn joint Memory track is a new, independent PicoBench campaign
owned by [Issue #70](https://github.com/Hackerismydream/pico-harness/issues/70).
Its only treatment axis is:

```text
control:   memory.backend = null
treatment: memory.backend = codecairn
```

Before any paid Trial, its credential-free Gate installs exact Pico and
CodeCairn wheels, proves cross-process store and Context recall through the
real Runtime path, verifies repository isolation and Memory-off zero backend
operations, and freezes a digest-bound Pair Manifest. The paid matrix uses
eight disjoint formal tasks, two variants, and two repetitions. A complete
negative result may close the evidence campaign but cannot become a positive
project claim.

The final formal experiment
`1c5496edfaa08212635f6218f9aaa55c3e942fcd1e79203a11a6b8c4d9b94623`
completed 32/32 Trials and 16/16 valid Pairs. CodeCairn passed 16/16 task
Verifiers while Memory-off passed 0/16; Recall@5 was 1.0, with zero stale
injections, zero cross-repository leakage, and zero Memory-off backend
operations. The result is ship-complete and measurement-valid, but
`positive_claim_eligible=false`: every hard-negative query returned three
rendered memories, producing an irrelevant-injection rate of 3.0 against the
frozen maximum of 0.05. The empty `cv-metrics.json` is therefore the
authoritative resume boundary.

The separate
[PicoBench task-effect v2 contract](picobench-task-effect-v2.md) is owned by
[Issue #77](https://github.com/Hackerismydream/pico-harness/issues/77), with
the installed campaign owned by
[Issue #79](https://github.com/Hackerismydream/pico-harness/issues/79).
Its credential-free Stage A freezes 24 realistic repository tasks, 100 labeled
retrieval cases, parent-owned Verifiers, unambiguous v2 metrics, and
independent retrieval, task-success, and efficiency Claim Gates. The scripted
96-Trial smoke proves task paths and offline rebuild behavior only. It makes no
paid call and is not task-effect evidence. The installed adapter consumes exact
Pico and CodeCairn wheels from a clean Stage C freeze, gives the real Agent only
repository read, artifact write, and bounded check tools, and records complete
Provider usage, cost, Memory injection, Tool receipts, and external Verifier
outcomes. CodeCairn remains an immutable treatment dependency during the
campaign.

The final task-effect v2 calibration experiment
`6fbc169ee80ff29e7b8822e6a26992856706a69eab71853ba3e08338410ed11f`
completed 12/12 task Trials and 10/10 retrieval cases. All task Trials ended
in Provider failure, leaving 0/6 valid Pairs, while all retrieval cases were
measurable. The campaign is ship-complete but measurement-invalid, and every
retrieval, task-success, efficiency, and positive Claim Gate is ineligible.
The formal 96-Trial matrix did not run. Issue #79 charged 1.29966592 CNY and
left no open reservation. The report digest is
`a5e4f79acd756276eb1b714dfc7959ac0e1e84a209df60d7b8f916412e66cde3`.
These calibration records are Provider-boundary evidence, not CodeCairn
task-effect evidence.

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
make picobench-codecairn-task-effect-smoke
make picobench-codecairn-task-effect-estimate
make picobench-codecairn-task-effect-ship
```

`make picobench-smoke` is credential-free and validates the contract,
deterministic Tracks, local MCP transport, and report rebuild.
`make picobench` performs the live Provider preflight and executes or resumes
the frozen Ship-1 plan. Re-running a complete plan performs no model calls and
rebuilds the report from the immutable manifest and stored evidence records.
`make picobench-codecairn-task-effect-smoke` is the separate credential-free
v2 task-validity, retrieval, regression, and report-rebuild Gate.
`make picobench-codecairn-task-effect-estimate` prints the calibration plus
formal worst-case projection without a Provider call. The Ship target requires
the exact installed-pair Stage C summary and a separately recorded numeric CNY
authorization before live calibration or formal evaluation.

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
| [PicoBench Ship-1 contract](picobench-ship-1.md) | Task packs, variants, metrics, statistics, artifacts, and Gates |
| [Ship-1 delivery analysis](../plan/analysis/picobench-ship-1.md) | Module decomposition, integration enumeration, dependency graph, and task split |
| [Delivery tasks](../plan/tasks/) | Smallest independently verifiable implementation slices |
