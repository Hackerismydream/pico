# Pico learning path

A study path through the retained Pico Runtime, in the order a Turn actually
travels: Spine, then the Agent Loop and its Tools, then the state layers a Turn
reads and writes, then the Skills and Plugins that extend it, then the hosts
that submit Turns, then the surfaces that carry a Turn outward, and finally the
opt-in Evolver that sits around all of it.

This is not a feature checklist and not a history of what was removed. Each
section names the exact entry files, what the layer owns, one hands-on
exercise, and the Gate that protects the layer. Whether a capability is backed
by deterministic, contract, live, or historical evidence is a separate
question, answered in [feature-evidence.md](feature-evidence.md).

Terms in this document are defined in [../CONTEXT.md](../CONTEXT.md); the
context entry point is [../CONTEXT-MAP.md](../CONTEXT-MAP.md).

## Before you start

Set up the source checkout once, following [dev.md](dev.md):

```bash
uv sync --all-extras
make build-tui
uv run pico --help
```

Gates are invoked by name throughout. Their commands, required environment
variables, and evidence outputs are documented in [dev.md](dev.md); this
document only says which Gate covers which layer.

## 1. Spine

Entry files:

- [`../pico/spine/scheduler.py`](../pico/spine/scheduler.py)
- [`../pico/spine/turn.py`](../pico/spine/turn.py)
- [`../pico/spine/runner.py`](../pico/spine/runner.py)
- [`../pico/spine/events.py`](../pico/spine/events.py)
- [`../pico/spine/delivery.py`](../pico/spine/delivery.py)
- [`../pico/spine/message.py`](../pico/spine/message.py)

Spine is the single backbone every Turn flows through: one entry,
`Scheduler.submit(TurnRequest)`, and one exit, `emit(Deliverable)`. It owns
per-conversation Lanes, which are simultaneously the ordering unit and the
cancellation unit, so a stalled conversation never blocks another. It owns
OriginPools, which gate concurrency separately for `USER` and for Runtime
origins such as `CRON` and `SUBAGENT`. It owns the Turn lifecycle events
(`TurnStarted`, `TurnFailed`, `TurnEnded`) that a runner is deliberately not
allowed to emit, and the `DeliveryHub` that routes each Deliverable to an
outlet. Spine never imports the agent side: `pico/spine/runner.py` declares the
`TurnRunner` protocol and the agent implements it, so the dependency points
one way.

Exercise: run the deterministic Spine subset and read one lane test end to end,
tracing a `TurnRequest` from `submit` to its terminal lifecycle event.
`test_success_emits_started_then_deliverables_then_ended` is the shortest path
through that sequence.

```bash
uv run pytest tests/test_spine_scheduler_lane.py -x
```

Gate: the deterministic V-D0 Spine subset inside `make test-retained`, plus
V-TE0 (`make verify-turn-evidence`) for the Turn terminal states Spine records.

## 2. Agent Loop and Tools

Entry files:

- [`../pico/agent/loop/main.py`](../pico/agent/loop/main.py)
- [`../pico/agent/spine_runner.py`](../pico/agent/spine_runner.py)
- [`../pico/agent/loop/recovery.py`](../pico/agent/loop/recovery.py)
- [`../pico/agent/loop/checkpoint.py`](../pico/agent/loop/checkpoint.py)
- [`../pico/agent/tools/registry.py`](../pico/agent/tools/registry.py)
- [`../pico/agent/tools/base.py`](../pico/agent/tools/base.py)
- [`../pico/agent/hook/base.py`](../pico/agent/hook/base.py)
- [`../pico/agent/subagent/manager.py`](../pico/agent/subagent/manager.py)

The Agent Loop is the one Turn Runner implementation Pico ships: it receives a
`TurnRequest` from Spine, assembles context, drives the model-call and
tool-execution Iterations, and emits Deliverables back through the Spine
callback. It owns iteration bounds, including the tools-disabled Synthesis call
made when a Turn hits `max_iterations`, and the Empty-Response Recovery policy
for a model that returns no text. The Tool Registry is the name-to-Tool table
the loop dispatches into; it runs each Tool under a timeout and returns a
`ToolResult` with an explicit failure bit, so a failed Tool stays visible to
both the model and the evidence layer instead of passing as a silent success.
Agent Hooks are the loop's extension point, chained through `CompositeHook`,
and the Subagent manager spawns background work that re-enters the Session as a
`SUBAGENT`-origin Turn rather than nesting inside the current one.

Exercise: execute one Turn against your configured Provider and watch which
Tools it dispatches.

```bash
uv run pico run -m "List the files in this workspace and summarize them"
```

Gate: the deterministic V-D0 Agent Loop and Tool subsets inside
`make test-retained`; V-TE0 additionally proves a Tool failure is recorded as a
completion with its own terminal state rather than a Turn failure.

## 3. Session, Context, and Memory

Entry files:

- [`../pico/session/manager.py`](../pico/session/manager.py)
- [`../pico/session/export.py`](../pico/session/export.py)
- [`../pico/context_engine/assembler.py`](../pico/context_engine/assembler.py)
- [`../pico/context_engine/curator.py`](../pico/context_engine/curator.py)
- [`../pico/context_engine/segments/`](../pico/context_engine/segments/)
- [`../pico/memory_engine/backend.py`](../pico/memory_engine/backend.py)
- [`../pico/memory_engine/consolidate/consolidator.py`](../pico/memory_engine/consolidate/consolidator.py)
- [`memory-plugin-architecture.md`](memory-plugin-architecture.md)

These three layers are what makes a Turn continuous rather than isolated.
Session owns the ordered, append-only record of Turns for one conversation,
keyed by `channel:chat_id`, plus the Portable Session Export that stays
verifiable after the source Session is deleted. The Context Engine owns the
prompt window: one `ContextAssembler` runs an ordered SegmentBuilder pipeline,
building the system prefix first and then budgeting history against that fixed
overhead, with the Curator as its Segment 6. The Curator is where token
pressure is handled without silent loss: a Fast Path passes history through
untouched, a Slow Path plans archives and retrievals, and a deterministic
Fail-Safe takes over whenever that plan is missing or invalid. Memory is
reached through the public backend contract, with the installed Myna
Plugin providing repository-scoped recall and durable post-Turn storage.
Reading these together answers the question the layers exist for: what a Turn
remembers, what it can retrieve verbatim, and what it can never lose silently.

Exercise: run the retained Session/Context/Memory pipeline tests, then inspect
and export a Session.

```bash
uv run pytest tests/test_agent_loop_memory_pipeline.py tests/test_default_context_engine.py -q
uv run pico sessions list
uv run pico sessions export <session-id>
```

Gate: the retained V-D0 Session and Context subsets plus the installed Myna
composition verifier. They prove normalized storage, fail-closed selection,
cross-process provenance, and Memory-off isolation. They do not prove task
effect, performance, or production success.

## 4. Skills and Plugins

Entry files:

- [`../pico/memory_engine/skill_forge/router.py`](../pico/memory_engine/skill_forge/router.py)
- [`../pico/memory_engine/skill_forge/fusion.py`](../pico/memory_engine/skill_forge/fusion.py)
- [`../pico/memory_engine/skill_local/local_pool.py`](../pico/memory_engine/skill_local/local_pool.py)
- [`../pico/context_engine/segments/skills.py`](../pico/context_engine/segments/skills.py)
- [`../pico/plugin/manifest.py`](../pico/plugin/manifest.py)
- [`../pico/plugin/discover.py`](../pico/plugin/discover.py)
- [`../pico/plugin/registry.py`](../pico/plugin/registry.py)
- [`memory-plugin-architecture.md`](memory-plugin-architecture.md)

Skills and Plugins are the two extension seams that do not require editing the
Runtime. SkillForge retrieves candidates from the local BM25/CJK-aware pool and
injects bounded survivors through the Skills segment; it is independent of the
selected Memory backend and there is no remote marketplace in the path. The
Plugin layer is manifest-driven: a `pico-plugin.toml` declares an id and version and
contributes `memory_backends` and `tools` entries, each naming a
`module:callable` factory. The Plugin Registry discovers manifests, activates
what is not disabled, resolves each factory by dynamic import, and fails closed
on a duplicate plugin id or contribution name. The host hands the user's
per-plugin config dict to the factory verbatim, which is why a plugin can be
configured without the Runtime knowing what the keys mean.

Exercise: list what is actually registered on your machine and open one Skill.

```bash
uv run pico plugins --verbose
uv run pico skills list
uv run pico skills get <skill-name> --with-body
```

Gate: the deterministic V-D0 SkillForge and Plugin subsets inside
`make test-retained`, including Turn attribution for an injected Local Skill.

## 5. Hosts

Entry files:

- [`../pico/cli/commands.py`](../pico/cli/commands.py)
- [`../pico/cli/_runtime_assembly.py`](../pico/cli/_runtime_assembly.py)
- [`../pico/cli/gateway_commands.py`](../pico/cli/gateway_commands.py)
- [`../pico/cli/_gateway_spine.py`](../pico/cli/_gateway_spine.py)
- [`../pico/cli/tui_commands.py`](../pico/cli/tui_commands.py)
- [`../pico/tui_rpc/server.py`](../pico/tui_rpc/server.py)
- [`../ui-tui/src/entry.tsx`](../ui-tui/src/entry.tsx)

A host is anything that submits a Turn: the CLI, the native TUI, and the
background Gateway. They are not three Runtimes.
`pico/cli/_runtime_assembly.py` is the one concrete composition of Config,
Plugin Registry, Memory backend, plugin Tools, Session manager, and Agent Loop
that all three share, and it also owns Memory backend, MCP, and Sandbox
teardown. Each host then supplies only what is genuinely its own: its Provider,
Cron service, interaction policy, optional model Router, and its outlet,
broker, and Turn Runner wiring. The TUI is the
one interactive local front end and reaches the Runtime solely over TUI-RPC, a
stdio pipe or Unix socket carrying Request/Response calls inward and
Notifications outward; it never imports Runtime internals. Reading the assembly
before any individual host is what keeps the three surfaces legible as one
system.

Exercise: inspect the assembled Runtime from the CLI, then start the TUI
against the same configuration.

```bash
uv run pico status
uv run pico doctor
uv run pico
```

Gate: V-P0 (`scripts/verify_distribution.py`) proves the installed package
boundary, and `make verify-runtime-hosts` replays one protected file-reading
task through CLI, TUI, and Gateway from that verified wheel against a
deterministic local endpoint. V-LP (`make verify-live-provider`) repeats the
same contract against one real Provider and is operator-run: it needs
credentials and is never satisfied by a skipped result.

## 6. Channels, Cron, and Tracing

Entry files:

- [`../pico/channels/contract.py`](../pico/channels/contract.py)
- [`../pico/channels/registry.py`](../pico/channels/registry.py)
- [`../pico/channels/manager.py`](../pico/channels/manager.py)
- [`../pico/channels/intake.py`](../pico/channels/intake.py)
- [`../pico/channels/outlet.py`](../pico/channels/outlet.py)
- [`../pico/channels/adapters/feishu/channel.py`](../pico/channels/adapters/feishu/channel.py)
- [`../pico/proactive_engine/schedulers/cron/service.py`](../pico/proactive_engine/schedulers/cron/service.py)
- [`../pico/tracing/trace.py`](../pico/tracing/trace.py)
- [`../pico/tracing/semconv.py`](../pico/tracing/semconv.py)
- [`../pico/tracing/usage.py`](../pico/tracing/usage.py)

These three share a section because they are the same question asked at the
edge: what entered, what was scheduled, and what can be proven afterwards. A
Channel is a platform adapter registered through `ChannelSpec`, which also
declares the adapter's Channel Maturity; intake normalizes and dedups inbound
events, the allowlist denies by default, and the outlet classifies a send
failure as retryable or terminal instead of collapsing both into an error.
Cron is the persistent user-scheduled path: it claims a fire, submits an
`Origin.CRON` Turn through the same Spine, and keeps pending fires claimable
across a Gateway restart while a completed one-shot job cannot fire twice.
Tracing is the write-side standard defined in
[TRACING_STANDARD_API.md](TRACING_STANDARD_API.md): one `spine.turn` root per
Turn carrying its terminal state, `session.turn` and every model, Tool, Memory,
Skill, and delivery span beneath it on one trace id, and usage rows that join
back by `trace_id` and `turn_span_id`. A Channel failure is a Delivery Outcome,
not a Turn terminal state, which is exactly the distinction the evidence Gate
below exists to protect.

Exercise: run the deterministic Channel Gates, check adapter readiness, then
open the Tracing viewer on a Turn you just ran.

```bash
make verify-channels
uv run pico channels status
uv run pico tracing
```

Gate: V-C0 and V-S0 (`make verify-channels`) for the Channel contract bundle
and the Channel security and isolation bundle; V-TE0
(`make verify-turn-evidence`) for the tracing, usage, and delivery join. V-LF
(`make verify-live-feishu`) is the operator-run live Feishu tracer bullet: it
requires real credentials and a human to provide the inbound stimulus, and no
deterministic Gate substitutes for it. The per-adapter contract matrix is
[specs/channel-evidence-gates.md](specs/channel-evidence-gates.md).

## 7. Evolver

Entry files:

- [`../pico/evolver/README.md`](../pico/evolver/README.md)
- [`../pico/cli/evolve_commands.py`](../pico/cli/evolve_commands.py)
- [`../pico/evolver/cli.py`](../pico/evolver/cli.py)
- [`../pico/evolver/orchestrator/loop.py`](../pico/evolver/orchestrator/loop.py)
- [`../pico/evolver/orchestrator/gates/pipeline.py`](../pico/evolver/orchestrator/gates/pipeline.py)
- [`../pico/evolver/candidate_manifest.py`](../pico/evolver/candidate_manifest.py)
- [`../pico/evolver/activation/artifacts.py`](../pico/evolver/activation/artifacts.py)
- [`specs/self-evolution-loop-sop.md`](specs/self-evolution-loop-sop.md)

Evolver is opt-in Beta and sits around the Runtime rather than inside it:
nothing runs until `pico evolve` is invoked with a run-spec. One Evolution Run
is durable and resumable from its journal, so `run`, `status`, and `finalize`
can each execute in a fresh process against the same `work_dir`. A candidate
becomes reviewable through its Candidate Manifest, which G5 binds to the exact
patch and rejects on digest drift, unsupported labels, paths outside the label
allowlist, or any attempt to touch sealed tests, scorers, gate math, or the
Evolver kernel. Evaluation ends in one of four Evidence Verdicts, and only a
fully measured, non-regressing `accepted` result counts as improvement; a
Provider or infrastructure failure is `failed`, never a product result.
Promotion selects a baseline inside the run and does not activate anything.
Activation is a separate manual step: a runtime candidate starts
`pending_human`, requires a Rollback Artifact by default, and the state record
never edits your checkout or moves `HEAD`.

Exercise: read the shipped run-spec template, then run the deterministic Gate
that covers the surface. `pico evolve check` validates a run-spec without
spending anything; the template ships with `/path/to/...` placeholders, so copy
it and fill them in before the check reports anything but a config error.

```bash
cat docs/examples/evolve_appworld.yaml
uv run pico evolve check --config <your-filled-in-copy>.yaml
make verify-evolver
```

Gate: V-E0 (`make verify-evolver`), the deterministic acceptance Gate for the
Evolver Beta. It covers the public command surface, readiness validation, the
four-way verdicts, Candidate Manifest G5 checks, scorer and path isolation,
manual runtime activation, rollback artifacts, and a fixture-backed
cross-process Evolution Run. V-E0 spends no live model calls, so a passing V-E0
is never a benchmark or production result.

## Where to go next

- [feature-evidence.md](feature-evidence.md) maps each retained capability to
  its implementation entry point, its strongest Gate, and what may honestly be
  claimed about it today.
- [dev.md](dev.md) holds the exact Gate commands, environment variables, and
  evidence outputs.
- [../CONTEXT.md](../CONTEXT.md) is the canonical glossary; use its term for a
  concept rather than coining a synonym.
