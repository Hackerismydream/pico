# PicoBench Ship-1 delivery analysis

> **Status: Historical delivery analysis.** GitHub Issue
> [#59](https://github.com/Hackerismydream/pico-harness/issues/59) accepted the
> scope and Gates, and the implementation now lives under
> `benchmarks/picobench/`. The gap analysis and estimates below record the
> pre-implementation decision; current contracts and generated campaign
> evidence own present behavior and measured claims.

## Outcome

Ship-1 converts five existing Pico architecture claims into reproducible
task-level measurements:

```text
Runtime
Context
Memory / Skill
Tool / MCP
Agent evaluation
```

It deliberately excludes crash recovery and external-side-effect reliability.
Those require Runtime state-model changes owned by Ship-2.

## Pre-implementation reality

| Capability | Current implementation anchor | Ship-1 gap |
| --- | --- | --- |
| Runtime | [`TurnRunner`](../../../pico/spine/runner.py), [`Scheduler`](../../../pico/spine/scheduler.py), [`AgentTurnRunner`](../../../pico/agent/spine_runner.py), and [`Runtime Assembly`](../../../pico/cli/_runtime_assembly.py) | request-level pressure evidence and full-path benchmark host |
| Context | [`ContextAssembler`](../../../pico/context_engine/assembler.py) and the current [factory](../../../pico/context_engine/factory.py) | frozen long-session tasks and a FIFO phase-B history-manager adapter |
| Memory | Session facts plus the [user-Memory segment](../../../pico/context_engine/segments/memory.py) and EverOS recall | anonymous recall observations, retrieval labels, and on/off task result |
| Skill | [`SkillForgeRouter`](../../../pico/memory_engine/skill_forge/router.py), Local BM25, EverOS semantic retrieval, and weighted RRF | source/rank observations and local-only comparison |
| Tool/MCP | [`ToolRegistry`](../../../pico/agent/tools/registry.py), [`ToolSearchStrategy`](../../../pico/agent/tools/tool_search.py), and [MCP Tools](../../../pico/agent/tools/mcp.py) | large-catalog real MCP comparison and stable failure metrics |
| Tracing/usage | [Tracing](../../../pico/tracing/) and [`UsageTracker`](../../../pico/token_wise/usage_tracker.py) | Trial-scoped aggregation and completeness findings |
| Evaluation | independent benchmarks, Gates, and unmounted EvalEngine | one frozen paired task protocol with deterministic Verifiers |

PinchBench Direct drives `AgentLoop.run_turn` without Scheduler, Lane, Runtime
Assembly, or Delivery. It can donate fixtures or task ideas but cannot be the
Ship-1 execution truth. EvalEngine is an Agent Hook and LLM-judge subsystem,
not an external task-level Verifier.

## Interface alternatives considered

### Independent scripts

One script per capability minimizes first-file cost but duplicates identity,
pairing, timeout, failure vocabulary, artifact persistence, and reporting.
Deleting the shared harness would not restore locality.

### Generic evaluation framework

A registry plus workflow/DAG language supports arbitrary experiments but makes
the caller learn nearly as much as the implementation. It risks duplicating
Scheduler and Agent Loop orchestration.

### Chosen deep module

One checkout-only PicoBench module exposes:

```python
run(spec) -> ExperimentRef
rebuild_report(ref) -> ShipReport
```

Task Packs provide internal adapters and narrow task formats. The module earns
its place because deleting it would spread plan identity, paired ordering,
failure classification, resume, evidence, and report logic across every Pack.

## Module decomposition

| Module task | Inputs | Outputs | Dependencies | Delivery task |
| --- | --- | --- | --- | --- |
| Core harness | ExperimentSpec, task/variant registries | ExperimentRef, Trial plan, terminal-record primitives | filesystem, Git identity | `picobench-001` |
| Runtime experiment seams | injected Context/Memory adapters, Provider observer | supported Runtime composition without private mutation | Agent Loop, Runtime Assembly | `picobench-002` |
| Runtime Pack | request workload and deterministic scripts | R0/R1 Trial Records | Core harness, Runtime seams | `picobench-003` |
| Context Pack | frozen histories and Verifiers | FIFO/Curator paired records | Core harness, Runtime seams | `picobench-004` |
| Memory/Skill Pack | corpus, learning/evaluation Sessions | retrieval and cross-session paired records | Core harness, Runtime seams, EverOS | `picobench-005` |
| Tool/MCP Pack | local MCP fixture and tasks | all-tools/disclosure paired records | Core harness, Runtime seams, MCP | `picobench-006` |
| Reducer and reports | immutable manifest, stored evidence records, and preregistered thresholds | Pair results, statistics, summary, CV metrics | Core harness | `picobench-007` |
| Ship campaign | all Pack versions and real Provider | frozen campaign and integrity verdict | all prior tasks | `picobench-008` |

## Integration enumeration

Each relationship below requires a task-level integration check with real
implementations. Unit tests at either side are insufficient.

| Creator/caller | Created/called dependency | Required integration | Task |
| --- | --- | --- | --- |
| Core harness | filesystem evidence adapter | atomic Trial Record and crash-tail recovery | `picobench-001` |
| Core harness | Pack adapter | task-by-variant expansion and terminal classification | `picobench-001` |
| Runtime Assembly | injected Context/Memory adapters | default hosts remain unchanged; experiment adapters are explicit | `picobench-002` |
| R0 driver | Scheduler/Lane/OriginPools | all accepted requests reach one terminal request state | `picobench-003` |
| R1 driver | Runtime Assembly plus Scheduler/AgentTurnRunner execution | real composition reaches Agent Loop, Session, Tool, and Delivery | `picobench-003` |
| Context Pack | Context Engine seam | the declared phase-B `history_manager` axis differs; Phase A and Tool definitions remain fixed | `picobench-004` |
| Memory Pack | recording `MemoryBackend` | real recall is unchanged while anonymous observations are captured | `picobench-005` |
| Skill Pack | local and EverOS sources | weighted-RRF source contributions and task injection are observable | `picobench-005` |
| Tool Pack | local MCP server | real transport registers the same catalog in both variants | `picobench-006` |
| Tool Pack | Tool Search | only Tool visibility differs; underlying Tools match | `picobench-006` |
| Reducer | immutable manifest plus stored evidence records | task-level effects, Pair coverage, and Claim Gates | `picobench-007` |
| Reducer | immutable manifest plus stored evidence records | report rebuild performs no Runtime or Provider calls | `picobench-007` |
| Make target | PicoBench interface | smoke/run/rebuild lifecycle | `picobench-008` |
| Campaign | configured real Provider | Comparison Block ordering, retries, usage, and failures remain symmetric | `picobench-008` |

## Delivery graph

```text
picobench-001 core
  |                \
  v                 v
picobench-002     picobench-007
Runtime seams     Reducer / reports
  |
  +---------------+---------------+---------------+
  v               v               v               v
picobench-003   picobench-004   picobench-005   picobench-006
Runtime Pack    Context Pack    Memory/Skill    Tool/MCP Pack
  \               |               |               /
   +---------------+---------------+--------------+
                           |
                           v
                    picobench-008
                    Ship campaign
```

`picobench-003` through `picobench-006` may run in parallel after the Runtime
seams land and their exact paths are confirmed not to overlap.
`picobench-007` may start after the core contract. The final campaign is
serial.

## Path and state isolation

Development and the final campaign must use clean worktrees so the source
digest matches the code that actually executes.

Each Trial also isolates:

```text
workspace
PICO_HOME
EverOS root
Session id
trace root
MCP process
evidence directory
```

No task may write raw reports or large assets into Git.

## Task sizing

| Task | Expected focused effort | Resume value |
| --- | ---: | --- |
| `picobench-001` | 2-3 days | evaluation rigor and reproducibility |
| `picobench-002` | 1-2 days | clean Runtime experimentation seam |
| `picobench-003` | 1-2 days | Runtime concurrency and full-path evidence |
| `picobench-004` | 2-3 days | Context token and outcome comparison |
| `picobench-005` | 2-3 days | Memory/Skill retrieval and reuse |
| `picobench-006` | 2-3 days | Tool/MCP scaling evidence |
| `picobench-007` | 1-2 days | Pair reduction, statistics, and rebuildable reports |
| `picobench-008` | 1-3 days plus Provider runtime | final task, token, latency, and retrieval metrics |

The target remains 8-12 focused development days by overlapping isolated Pack
work and starting with a 12-task, two-repetition calibration. This is a stretch
target rather than an estimate guarantee. If the time box
is exceeded, reduce task count temporarily; do not weaken Pair symmetry,
Verifier independence, failure retention, or artifact rebuild.

The final campaign still requires the frozen 24-task, three-repetition plan
with a three-arm Memory/Skill Pack.

## Calibration and final campaign

Calibration:

```text
Context:     4 tasks x 2 variants x 2 repetitions = 16
Memory/Skill: 4 tasks x 3 variants x 2 repetitions = 24
Tool/MCP:    4 tasks x 2 variants x 2 repetitions = 16
E2E Trial total:                                 56

User Memory retrieval: 10 queries x 1 config     = 10
Skill retrieval:       8 queries x 3 configs     = 24
Retrieval Case total:                             34
```

Calibration uses task ids disjoint from the formal 24-task suite and finds
mechanical harness, fixture, Verifier, and Provider-contract defects. Claim
Rules are frozen before calibration and cannot change in response to effect
sizes. Any mechanical change receives a new digest and reruns calibration.

Final:

```text
Context:      8 tasks x 2 variants x 3 repetitions = 48
Memory/Skill: 8 tasks x 3 variants x 3 repetitions = 72
Tool/MCP:     8 tasks x 2 variants x 3 repetitions = 48
E2E Trial total:                                   168

User Memory retrieval: 80 queries x 1 config       = 80
Skill retrieval:       60 queries x 3 configs      = 180
Retrieval Case total:                               260
```

Final task results are not used to rewrite task definitions or thresholds.
The three Packs have different controls, so Ship-1 reports Pack-specific
single-axis effects. It does not claim a unified Pico-full overall lift.

## Accepted authority boundary

Issue #59 accepted the following boundary:

- title: `feat(evaluation): add PicoBench agent application Ship-1`;
- the problem statement from
  [`docs/evaluation/picobench-ship-1.md`](../../evaluation/picobench-ship-1.md);
- tasks `picobench-001` through `picobench-008`;
- G0 through G6 as acceptance Gates;
- explicit exclusion of Ship-2 recovery, model routing, new Channels,
  Provider expansion, EvalEngine mounting, and public CLI;
- evidence rule that negative results may complete Ship but cannot earn a
  positive claim;
- explicit authorization for the optional Context-engine factory seam in
  `pico/agent/loop/main.py`, `pico/cli/_runtime_assembly.py`, and
  `pico/context_engine/factory.py`, plus the three retained host/Context test
  files named by `picobench-002`; without that authorization,
  `picobench-002` is blocked;
- one Provider/model identity and an approved campaign cost ceiling.

The accepted authority is recorded in the task index and individual task
cards. It does not authorize Ship-2 recovery or substitute for result evidence.

## Final deliverables

Tracked:

- PicoBench implementation and tests;
- frozen suite, tasks, fixtures, and Verifiers;
- `make picobench-smoke` and `make picobench`;
- schemas and concise rerun documentation;
- updated current-state docs after results land.

Untracked:

- raw prompts and model responses;
- live Memory content;
- Trial artifacts;
- generated `REPORT.md`;
- `summary.json` and `cv-metrics.json`;
- Provider credentials.

## Review focus

Review blocks delivery when:

- a Pack bypasses Scheduler for a full-path claim;
- Context, Memory, Skill, or Tool comparisons change more than one axis;
- a Verifier depends on model self-report;
- host execution is described as verifier isolation;
- `TurnOutcome.usage` is used as total Trial usage;
- repetitions are treated as independent tasks;
- Tool Schema estimates are described as billed tokens;
- failed or timed-out Trials disappear from results;
- negative results are copied into positive CV claims;
- Trial-level resume is described as crash recovery.

The reporting state must record separately:

```text
ship_complete
measurement_valid
positive_claim_eligible
```

A negative result may be complete and valid. A treatment-drifted or
under-covered result is invalid even when its observed number is positive.
Positive Claim Eligibility implies both Ship Completeness and Measurement
Validity.
