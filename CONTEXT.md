# Pico Runtime

> **Status: Pico v1 implementation glossary.** Product and Python module terms
> use the canonical Pico vocabulary defined here.

The Python agent runtime: receives messages from chat channels, runs the agent loop
against LLM providers, and hosts the feature engines (context, memory, eval)
plus the CallEfficiency layer.

## Language

### Agent Core

**Session**:
The ordered, append-only record of turns for one conversation, identified by a
session key (`channel:chat_id`). Identity lives in the `chat_id` slot: a TUI/CLI
session mints an opaque, sortable `chat_id` (`%Y%m%d_%H%M%S_xxxxxx`), so one surface
can hold many sessions while the `session_key={channel}:{chat_id}` invariant is
unchanged. Channel is a dimension (key prefix + store subdirectory + metadata
field), not part of the user-facing identity.

**Session id** (user-facing term only):
The bare `chat_id` value shown to and accepted from users (the channel prefix is
stripped for display, re-prepended to form the session key). Presentation term; in
code the value lives in the `chat_id` field and the composite is the `session_key`.

**Portable Session Export**:
A canonical JSON envelope containing the complete Session payload, a rendered
Markdown transcript, and a SHA-256 digest over the payload. It remains
verifiable after the source Session is deleted and is the public export format.
_Avoid_: "transcript export" — the Markdown view is only one field and is not
the portable record.

**Turn**:
One complete agent reaction: from an inbound message entering the agent loop to the
agent's final response, including every LLM call and tool execution in between.
Each Cron firing starts a turn of its own; a confirm round-trip pauses a turn,
it does not end it.
_Avoid_: calling a single LLM round-trip a turn

**Iteration**:
One LLM call plus the tool executions that follow it, inside a turn.

**Agent Loop** (`agent/loop/`):
The turn orchestration engine: receives a `TurnRequest` from the Spine, assembles context,
drives the LLM + tool-execution iterations, consolidates memory, and emits `Deliverable`
events via the Spine `emit` callback. Exposed to the Spine via `AgentTurnRunner`.
_Avoid_: calling a single LLM call the "agent loop" — the loop spans all Iterations of one turn.

**Runtime Assembly** (`cli/_runtime_assembly.py`):
The concrete shared composition of Config, Plugin Registry, Memory Backend, plugin Tools,
Session Manager, CallEfficiency Provider decorator, and Agent Loop used by CLI, TUI,
and Gateway. Each host supplies its Provider, Cron service, interaction policy, and
optional model Router, then retains its own outlet, broker, Channel, and Turn Runner
wiring. The assembly owns CallEfficiency, Memory Backend, MCP, and Sandbox teardown.
_Avoid_: "Runtime factory" or "lifecycle Interface" — this is one concrete composition
with three real host consumers, not an implementation hierarchy.

**TUI Runtime Host** (`cli/_runtime_host.py`):
The TUI-owned lifecycle module that builds Runtime Assembly off the TUI-RPC
event loop, exposes it through ``start`` / ``acquire`` / ``close``, and keeps
handshake readiness independent from Runtime construction. It does not replace
Runtime Assembly or change the other Runtime hosts.

**Turn Runner**:
The behavioural `Protocol` seam between Spine and an agent implementation:
`async run(req, emit, drain) → TurnOutcome`. Spine never imports the agent side; the agent
supplies `AgentTurnRunner` (wraps `AgentLoop`). Gateway and TUI variants also exist.
`TurnOutcome` carries Usage plus successful/failed Tool-call counts so every host
can verify the same completed Turn without parsing rendered text; the worker copies
those counts into `TurnEnded` for fire-and-forget hosts. A terminal Provider error
raises into `TurnFailed` instead of becoming a normal completion.
_Avoid_: conflating with Agent Loop — Turn Runner is the Protocol; Agent Loop is one implementation.

**Agent Hook** (`agent/hook/`):
The turn-loop extension point: an `AgentHook` ABC with five async phases
(`before_user_inbound`, `before_iteration`, `before_execute_tools`,
`after_iteration`, `after_send`).
Multiple hooks chain via `CompositeHook`. The EvalEngine source provides three
concrete implementations, but the shared Runtime Assembly does not mount them.
_Avoid_: "callback" or "middleware" — neither captures the phase-specific, chain-aware semantics.

**Subagent** (`agent/subagent/`):
A background agent task spawned by `SubagentManager`. Runs with its own tool set; its result
re-enters the session as a `SUBAGENT`-origin `TurnRequest` via Spine submit. Bounded by
`max_concurrent` (default 4) and a per-session hourly rate limit. A completed result,
execution failure, and exhausted Iteration budget are represented by one
`SubagentOutcome` carrying a typed status and result. Re-entry happens once, after executor
cleanup; quota refusal is a failed Tool result and starts no task. Session cancellation
propagates to the background task without re-entering the parent Session.
_Avoid_: conflating with a Turn — a Subagent lives outside the main turn and re-enters via Spine.

**Tool** (`agent/tools/`):
An agent capability behind a uniform `Tool` ABC (name, parameter schema, async
`execute`). Built-ins: file read/write/edit/list, grep/find, exec, web search/fetch,
message, ask_user, spawn (Subagent), MCP, and skill read/use.
_Avoid_: "function" — a Tool is the agent-facing capability, not a Python function.

**Tool Capability** (`agent/tools/execution.py`):
The declarative execution properties attached to a Tool: effect and concurrency
safety. An undeclared Tool uses the conservative `unknown` effect and is never
scheduled concurrently.

**Tool Execution Context** (`agent/tools/execution.py`):
The immutable call identity and Turn provenance propagated by the Tool Registry:
call id, Session key, Iteration, Origin, and optional parent call id. Progressive
`tool_call` dispatch derives a child context and adds resolved target identity to
the parent Tool Event.

**Tool Invocation** (`agent/tools/execution.py`):
One Tool name and arguments paired with its Tool Execution Context. The Tool
Registry accepts Invocations for both single-call and ordered batch execution.

**Tool Registry** (`agent/tools/registry.py`):
The name→`Tool` table the Agent Loop dispatches into: resolves a tool by name and runs
its `execute` under a timeout, returning a string-compatible `ToolResult` with an
explicit failure bit. Error text remains available to the model for recovery; the
corresponding completed `ToolEvent` sets `failed=True` so Hosts and evidence code do
not count the execution as a silent success. Registration rejects an existing name
unless replacement is explicit. Batch execution runs only consecutive
read-only, concurrency-safe Invocations in parallel with at most four active calls;
unknown, write, execute, and external calls are serial barriers, and results retain
model call order.

**Checkpoint** (`agent/loop/checkpoint.py`):
A once-per-turn commit of the workspace into a shadow git repo (separate from the
user's `.git`), so an interrupted or failed turn can be rolled back.
_Avoid_: "shadow git" as the term — Checkpoint is the per-turn snapshot it produces.

**Empty-Response Recovery** (`agent/loop/recovery.py`):
The opt-in policy for when the model returns no text: re-feed its reasoning (PREFILL),
inject a nudge after a tool call (NUDGE), or plain RETRY — each bounded by
`RecoveryLimits`; otherwise the turn COMPLETEs.
_Avoid_: calling the whole mechanism a "nudge" — nudge is one of its modes.

**Synthesis**:
The tools-disabled final LLM call the Agent Loop makes when a turn hits `max_iterations`
(default 40): it summarizes progress and returns partial results, and the turn ends with
status `interrupted`.
_Avoid_: "timeout" — Synthesis is iteration-bounded, not time-bounded.

**Personalizer** (`agent/personalizer/`):
The four-step preference flow wrapped around a turn: classify whether a preference
question is needed, ask it, run the Agent Loop, then post-learn signals from the
finished turn.

**Context Builder** (`agent/context/`):
The bootstrap/identity renderer (`ContextBuilder`) that loads Bootstrap Files and the
runtime-context block, feeding the Context Engine's segments.
_Avoid_: conflating with `ContextAssembler` — Context Builder renders identity pieces;
the Context Engine assembles the whole window.

**Spine** (`spine/`):
The single backbone every turn flows through: one entry
(`Scheduler.submit(TurnRequest) → TurnHandle.result()`) and one exit (`emit(Deliverable)`).
Per-conversation **Lanes** are the unit of both ordering and cancellation. Deliberately
not a broadcast bus — replaces the dormant `bus/` pub/sub.
_Avoid_: "the bus" — there is no Bus; "queue" for Lane — Lane is a serial+cancel domain.

**Lane**:
The per-conversation serial execution domain inside the Scheduler: runs one turn at a time
and is the unit of cancellation. A stalled Lane never blocks other Lanes.
_Avoid_: conflating Lane with OriginPools — different dimensions (ordering vs. concurrency).

**TurnRequest**:
The single input to Spine: carries `origin`, `source`, `text`, `media`, and `busy` policy.
Replaces the old `InboundMessage`.

**Deliverable** (= `RunnerEvent`):
The union of all content-type events a runner can emit: `Text | MediaOut | StreamDelta |
Reasoning | Notice | ToolEvent`. Routed to delivery outlets by the `DeliveryHub`.
Replaces the old `OutboundMessage`.
_Avoid_: conflating Deliverable with lifecycle events (`TurnStarted`/`TurnFailed`/`TurnEnded`) —
those are emitted by the Spine worker, not a runner.

**OriginPools**:
Per-origin concurrency gates: a `USER` pool and a `system` pool for Runtime origins
(`CRON`, `SUBAGENT`), sized independently with no borrowing.
A user turn never waits on a system task's LLM slot.

### Turn Evidence

**Turn Trace**:
The one trace a Turn owns (`pico/tracing/`): rooted at the `spine.turn` span opened by
`Lane._run_turn`, with the Agent Loop's `session.turn` and every model, Tool, Memory,
Skill, and delivery span beneath it on the same `traceId`.
_Avoid_: calling `session.turn` the root — it is the Agent Loop's execution of the Turn,
a child of the Spine root that owns the lifecycle events.

**Turn Terminal State**:
The single outcome recorded on `spine.turn` as `spine.outcome`: `completed`,
`completed_with_tool_failure`, `provider_failed`, `error`, or `cancelled`
(`pico/tracing/semconv.py:SPINE_OUTCOMES`). A Tool failure is a completion with its own
value, not a Turn failure.
_Avoid_: collapsing cancellation into error — they are separate lifecycle paths
(`TurnFailed(cancelled=True)` vs `cancelled=False`).

**Delivery Outcome**:
What a `channel.deliver` span records for one terminal Deliverable: `delivered`,
`dropped`, or `no_outlet` (`pico/tracing/semconv.py:CHANNEL_OUTCOMES`). A Channel failure
is a delivery terminal, not a Turn terminal — a completed Turn can have a dropped reply.

**Turn Evidence Report**:
The `V-TE0` artifact written by `scripts/verify_turn_evidence.py` to
`.pico/evidence/turns/turn-evidence-report.json` (schema `pico.turn.evidence.v1`):
per-Turn join summaries, per-check status, and detected contradictions. Stores ids,
labels, and counts only.
_Avoid_: treating it as a release ledger — it gates one deterministic correlation
scenario, not a release.

### Scheduling

**Cron** (`proactive_engine/schedulers/cron/`):
The persistent user-scheduled execution path: persist a job, claim its fire,
submit an `Origin.CRON` Turn through the Spine, record the outcome, and deliver
the result. Pending fires remain claimable across restarts, while completed
one-shot jobs cannot fire again. Terminal diagnostics distinguish failed,
cancelled, expired, and incompatible jobs.
_Avoid_: calling Cron self-initiated — the user explicitly scheduled it

### Channels & Front-ends

**Channel**:
A platform adapter (Feishu, QQ, or WeCom) that connects an external chat platform
to the Runtime; managed by the ChannelManager in gateway mode.
_Avoid_: calling the TUI a channel — `channel="tui"` on a message is a routing tag, not a Channel

**Channel Maturity**:
The evidence level a Channel declares through `ChannelSpec.maturity`, surfaced by
`pico channels list`, `pico channels status`, `pico doctor`, and onboarding. `beta`
means only the deterministic Channel contract bundle (V-C0) and the deterministic
Channel security and isolation bundle (V-S0) cover the adapter; `live-gated` means a
live Channel gate against a real bot has also passed.
_Avoid_: reading `beta` as unfinished code — it names the evidence behind the adapter,
not its code quality

**Issue Proposal**:
A Maintainer-curated Bug or maintenance request promoted from an authorized Channel by replying
`/issue` to a report, or by sending `/issue <description>`. It persists the promotion message,
Chat, Maintainer, and report text under a stable local identifier,
but does not become a GitHub Issue. The identifier is diagnostic state rather than the user-facing
handle: the Channel presents the report title and source link, and a Maintainer confirms it by replying
`/fix` to that report. Explicit proposal identifiers remain accepted for recovery and automation.
Publication stays separate under the project's GitHub policy.
_Avoid_: "Issue" — the proposal has no GitHub URL or external lifecycle yet.

**Maintenance Job**:
A persistent, maintainer-authorized Issue repair attempt that runs outside the shared Channel
Session. It binds the source message, Issue or Issue Proposal reference, repository Base Revision, isolated repair
worktree, configured checks, progress stages, and terminal result. Public Channel messages cannot inject into it.
_Avoid_: "maintenance Turn" — the Agent Turn is one execution step inside the longer Job.

**PR Candidate**:
The local evidence packet produced only after a patch applies to a clean worktree at the recorded
Base Revision and all configured verifier commands pass there. It contains the patch, changed-file
list, commands, exit codes, logs, and verdict. The Channel returns the readable verdict and attaches
the review report and patch to the originating conversation; it does not Push, create a PR, or authorize release.
_Avoid_: "PR" — no external GitHub object exists.

**TUI**:
The terminal front-end (`ui-tui/`) and the only interactive local front-end; talks to
the Runtime solely via TUI-RPC. Not a Channel.

**CLI**:
The command-line host for operations and local conversation. `pico run` starts
the interactive REPL, while `pico run -m "..."` executes one Turn and exits.
Bare `pico` launches the TUI.

**Routing Tag**:
The `channel` field on a `TurnRequest`; names the recipient — a Channel, or the TUI.

### Call Efficiency

**CallEfficiency**:
The Runtime-owned policy at the Provider-call boundary. It prepares the final
request after Tool filtering, normalizes Provider Usage into one semantic model,
estimates cost, and appends a correlated Call Record. Shared Runtime Assembly
installs exactly one instance and one stable Provider decorator for CLI, TUI,
and Gateway hosts; Runtime-owned background components share that decorator.
_Avoid_: calling the active Runtime subsystem TokenWise; TokenWise is the historical
compatibility surface and benchmark lineage.

**Call Efficiency Mode**:
The configured request policy: `off`, `observe`, or `optimize`. `observe` records
normalized Usage without changing the request and is the default. `optimize`
additionally owns explicit Anthropic cache breakpoints. DeepSeek and OpenAI cache
behavior remains Provider-automatic in every mode.

**Call Record**:
The versioned telemetry unit for one Provider attempt: requested, attempted,
actual, and accounting model identities; normalized fresh/output/cache/reasoning
tokens; attempt outcome and error category; estimated cost; cache policy;
findings; Session key; and Trace lineage.
Retries and fallback attempts are distinct records. Unknown pricing stays
`None`, and ambiguous Provider Usage is marked incomplete rather than priced.

**TokenWise**:
The historical Strategy, schema, and experiment compatibility surface under
`pico/token_wise/`. Its imports and frozen `pico.picobench.tokenwise-cost.*`
schemas remain valid, but Runtime request ownership belongs to CallEfficiency.

**TokenStrategy**:
One historical extension measure, implemented as a `TokenStrategy` ABC
with `before_llm_call` (may rewrite messages / tools / model) and `after_llm_call`
(observes usage) hooks; e.g. usage tracking, cache optimization, smart routing.
_Avoid_: bare "Strategy"

**StrategyRegistry**:
The ordered legacy chain that invokes registered
TokenStrategy's `before_llm_call` / `after_llm_call` hooks in registration order.
`before` errors propagate (a bad request fails fast); `after` errors are logged and
swallowed so telemetry never crashes the turn.

**UsageTracker**:
The retained historical TokenStrategy (`"usage_tracker"`) that records each call's UsageSnapshot and
rolls token counts and USD cost up into per-session, per-day, and lifetime aggregates.

**CacheOptimizer**:
The retained historical TokenStrategy (`"cache_optimizer"`) that places Anthropic's ≤4 ephemeral
`cache_control` breakpoints adaptively (tools tail + system tail + a rolling message-tail
window). A Hermes-faithful `SystemAndTailCacheStrategy` ships alongside as an A/B reference.

**UsageSnapshot**:
The historical TokenWise projection of a Call Record: input / output / cache-read /
cache-write / reasoning tokens plus the estimated USD cost. Cost is ``None`` when
the model has no known price; zero is reserved for a priced call whose computed
cost is actually zero. UsageTracker rollups keep their token totals but expose an
unknown aggregate cost if any included call is unpriced.

**Provider**:
An LLM vendor adapter (`providers/`: Anthropic, OpenAI, Gemini, …), shared by the
agent loop and the Curator.
_Avoid_: conflating provider (vendor) with model (a model name a provider serves)

### TUI-RPC

**TUI-RPC**:
The single transport between Runtime and TUI (stdio pipe / Unix socket), carrying two
message kinds: Request/Response (TUI → Runtime method calls) and Notification
(Runtime → TUI one-way events).
_Avoid_: calling a Notification "the bus" or "broadcast" — Spine events never cross into the TUI directly

**Turn Event**:
A typed payload streamed to the TUI over Notifications while a turn runs
(e.g. `cron.delivered`, `confirm.request`).

**Subscription**:
A TUI client's registration to receive turn events for a session.

**Confirm Round-Trip**:
The interaction pattern for destructive operations: one `confirm.request` Notification
out, the Runtime request pauses, one answering Request back.

### Context

**Context Engine** (`context_engine/`):
The layer that assembles each turn's LLM window. One unified engine —
`ContextAssembler` (`context_engine/assembler.py`) — runs an ordered pipeline of
SegmentBuilders in two phases: Phase A builds the system prefix in parallel, Phase B
budgets history serially against that fixed overhead. The historical
`legacy` / `curator` / `default` engine split was collapsed into this one engine;
`engine:` survives only as a backward-compat config alias.
_Avoid_: describing "legacy" and "Curator" as two separate engines — there is one
engine and the Curator is its Segment 6.

**SegmentBuilder**:
A pluggable contributor to the prompt; each builder produces one Segment for a fixed
slot in the pipeline. Builders run in `order`, optionally flagged `needs_prefix` to
defer into Phase B.

**Segment**:
A SegmentBuilder's uniform output: system-slot text, optional history (only the
Curator sets this), and metadata merged into the assembled context.

**Prompt Segments**:
The ordered blocks `ContextAssembler` renders into the system prompt, one per
SegmentBuilder: `# Pico` (identity), the Bootstrap Files block, `# Memory`
(host `user.md` plus selected-backend recall), `# Active Skills` (always-on) and `# Skills`
(SkillForge-routed candidates — see SkillForge), and `# Curator Working State`
(Segment 6).
_Avoid_: treating the system prompt as one opaque blob — each segment has an owner and order.

**Curator**:
An internal, bounded agent loop whose only job is to build the main agent's next
context window; wired in as Segment 6 (`CuratorSegmentBuilder`). It never answers the
user and never runs user-facing tools.
_Avoid_: calling legacy's lossy summarization "curating"

**Fast Path**:
Curator's zero-LLM route, taken when history is under the pressure threshold:
full history passes through unchanged.

**Slow Path**:
Curator's small-model agent loop, run under context pressure: inspects the Manifest,
archives/retrieves, and submits a ContextPlan that a deterministic assembler validates.

**ContextPlan**:
The Curator's structured output that the deterministic assembler validates and applies:
which message ids and archive refs to include, which to drop, plus memory sections and
the Working State injection.

**Fail-Safe**:
The deterministic fallback when the Slow Path errors or produces no valid plan:
protected + most relevant + most recent messages, no LLM involved.

**Historical Continuity Evidence**:
The removed EverOS V-O0 artifact that separated deterministic Session,
Context, and Turn checks from real Provider execution. It remains historical
evidence for its recorded commit, not a current Memory Gate.

**Archive**:
Curator's lossless eviction: messages written verbatim to disk with a reference,
retrievable word-for-word later.
_Avoid_: archive vs Consolidation confusion — Archive loses nothing

**Consolidation**:
The legacy path's lossy distillation: when the prompt outgrows the window, old
messages are summarized into memory notes and leave the live history view; the
originals never return to context.
_Avoid_: summarize, compact (ambiguous between this and Archive)

**Manifest**:
Curator's per-message metadata index for one session (tokens, snippet, relevance,
protected, archived) — what the Slow Path reads instead of full history.

**Working State**:
The distilled session notes (goals, open threads, decisions) the Curator maintains
and injects into the main agent's system prompt so evicted facts stay present.

### Memory

**EverOS** (historical):
The removed Pico memory-backend integration. Its bundled Plugin, direct
dependency, dual-track Skill source, feedback routing, onboarding, and
`understand_media` Tool are absent from the current Runtime. Dated evidence
remains valid only for the commits and experiments that produced it; Pico
neither reads nor deletes operator data left by that integration.

**Myna Memory Adapter**:
The Myna-owned `pico.plugins` Implementation of Pico's `MemoryBackend`
Interface. It binds the Pico Workspace to an initialized Myna repository,
maps user-track recall to repository recall, captures Session-normalized
after-Turn slices, and returns one compiled Recall Context as a concrete Pico
`Memory`. The installed Adapter is Pico's current default backend.
_Avoid_: Myna backend in Pico core - Pico owns the Interface and default
selection; Myna owns the Adapter.

**Pico Source Journal** (Pico Harness v0.2):
The Myna-owned append-only source that durably records persisted Pico
after-Turn slices before Myna imports them as Agent Trace. Boundary
`pico_turn_end` closes an imported slice without asserting task success. The
Journal supports prefix replay and crash-tail recovery; it is not the mutable
Pico Session JSONL and does not provide mid-Turn recovery.
_Avoid_: Session mirror, Task journal.

**SkillForge** (`memory_engine/skill_forge/`):
A Local Skill retrieval and injection subsystem. The active Runtime resolves
the local BM25/CJK-aware source without Provider calls: explicit matches inject
bounded Skill bodies, ambiguous matches expose compact ``SKILL.md`` references
for the main Agent Loop to read, and unrelated matches abstain. It does not
retrieve remembered Skills from the Memory backend. The rewriter, LLM gate, and
generic RRF helpers remain for historical benchmark reconstruction and
third-party callers, outside the active first-Turn path.

**Episode**:
A distilled event note the Consolidation step writes to `episodes.md`.

**Profile**:
The user-profile sections in `user.md`, refreshed when their tags run hot.

**Foresight**:
A prediction the Memory Engine derives about the user's likely future behavior
(each carries prediction / time-window / confidence), written by the consolidator.
_Avoid_: treating Foresight as a notification or scheduled task — it is stored
memory, not a live trigger.

**Consolidator** (`memory_engine/consolidate/`):
The Memory Engine component (`MemoryConsolidator`) that performs Consolidation —
under session-token pressure it annotates evicted message chunks into Episodes,
refreshes hot Profile sections, and (opt-in) emits Foresight. The agent loop skips
it when the Curator Context Engine is active.
_Avoid_: conflating with the Curator — the Curator builds the context window
losslessly; the Consolidator is the legacy lossy path that writes long-term memory.

### Plugins

**Plugin** (`plugin/`):
A component declared by a `pico-plugin.toml` manifest (`[plugin]`: `id`, `version`, optional
`bundled` / `enabled_by_default`). It contributes capabilities via
`[[plugin.contributes.<kind>]]` arrays — currently `memory_backends` and `tools` — each naming
a `factory` (`module:callable`). The host passes the user's `plugins.config["<id>"]` dict
verbatim to the factory as `PluginContext.config`.

**Plugin Registry** (`plugin/registry.py`):
The `PluginRegistry` discovers manifests, activates those not in `plugins.disabled` (respecting
`enabled_by_default`), resolves each `module:callable` factory by dynamic import, and registers
contributions into per-kind tables — deduping plugins by `id` and contributions by `name`
(`PluginConflictError` on collision). `build_memory_backend()` / `build_tool()` construct a
contribution with a fresh `PluginContext`.

### Security & Access

**AUTH** (`auth/`):
Authentication & authorization primitives (e.g. allowlist).

**SECURITY** (`security/`):
Network access control (e.g. `network.py`).

### Execution & Evaluation

**SandBox** (`sandbox/`):
The command-execution boundary. Host execution (`none`) is the default;
`boxlite` provides opt-in microVM isolation and owns the debug server and VM
lifecycle. Explicit isolation modes fail closed when BoxLite is unavailable.

**EvalEngine** (`eval_engine/`):
An unmounted evaluation subsystem: task judging and cognitive coordination,
implemented as three `AgentHook` instances (`BeforeIterationHook`,
`AfterIterationHook`, `ToolAuditHook`). The source is tested independently;
the shared Runtime Assembly does not currently add these hooks to `AgentLoop`.

**EvalJudge** (`eval_engine/judge/`):
The single-call LLM judge behind the EvalEngine's task-completion check: it compares the
turn's original user goal against the final response and returns a JudgeVerdict. Any error
path returns `unknown`, so the judge can never crash the Agent Loop.
_Avoid_: "task judge" as a class name — the class is `EvalJudge`.

**JudgeVerdict**:
The three-state outcome an EvalJudge returns: `completed` (goal addressed), `failed`
(visible error / missed objective), or `unknown` (indeterminate). The `AfterIterationHook`
writes completed/failed (never unknown) into `HISTORY.md`.

**PicoBench** (`benchmarks/picobench/`):
The checkout-only Agent application evaluation module delivered by Ship-1. It
executes frozen task variants through Pico's existing Runtime, runs parent-owned
deterministic Verifiers, reduces paired results, and rebuilds reports from an
immutable manifest and stored evidence records. It does not enter the wheel and
does not replace EvalEngine, Evolver, or V-R0.
_Avoid_: "EvalEngine v2" or "benchmark Runtime" -- PicoBench consumes the
Runtime and evaluates task outcomes; it does not orchestrate Agent Iterations.

**Experiment Plan** (PicoBench):
The immutable identity of one suite version, task/variant matrix, Pico commit,
Provider/model configuration, budgets, retry policy, and evidence schemas.
Secrets, machine-specific output paths, and generated timestamps are excluded
from its canonical digest.

**Task Pack** (PicoBench):
A narrow family of tasks that owns one task schema, one Verifier family, and a
fixed variant matrix. A Task Pack may compile more than one comparison, but
every Pair inside it changes exactly one Treatment Axis.

**Trial** (PicoBench):
One task, one variant, and one repetition executed in isolated state roots. A
Trial may contain multiple Turns and attempts.
_Avoid_: conflating with a Turn or an Evolution Run.

**Retrieval Case** (PicoBench):
One frozen retrieval query executed under one declared retrieval configuration.
It records labeled relevance, anonymous ranked results, injection decisions,
terminal evidence, and immutable attempts without pretending that a retrieval
query is an Agent Trial. User Memory and Skill fusion use separate Retrieval
Case suites and metric namespaces.

**Deterministic Verifier** (PicoBench):
Parent-owned code that decides task success from files, structured state,
receipts, digests, or Runtime evidence. Model final text and LLM judges may
provide diagnostics but cannot determine the Verifier result.

**Comparison Block** (PicoBench):
Every variant for one Task Pack task and repetition. The variants execute in a
digest-derived rotating order and share one block-attempt number; Provider or
infrastructure contamination reruns the complete block. This keeps a shared
arm in a three-arm Memory/Skill experiment on one selected block attempt.

**Treatment Axis** (PicoBench):
The one declared behavior allowed to differ between the baseline and treatment
Trials in a Pair, such as the phase-B history manager, user Memory recall,
Skill source set, or Tool disclosure. Any undeclared variant drift invalidates
the Pair.

**Trial Record** (PicoBench):
The digest-bound terminal evidence record for one planned Trial. It preserves
attempts and keeps Trial status, Turn terminal, delivery outcome, and
deterministic Verifier result as separate state dimensions.

**Pair** (PicoBench):
Baseline and treatment Trials with the same task, repetition, workspace seed,
model, budget, Tool catalog, timeout, and retry policy. Provider or
infrastructure contamination on any arm requires a Comparison Block rerun; a
product failure is retained.

**Measurement Validity** (PicoBench):
Whether treatment isolation, Pair coverage, failure retention, and statistical
rules make a result interpretable.

**Ship Completeness** (PicoBench):
Whether every planned Trial and Retrieval Case reached a terminal record and
the identity, integrity, failure-retention, and report-rebuild Gates passed.
Completeness does not imply that a treatment improved the product.

**Positive Claim Eligibility** (PicoBench):
Whether a complete, valid measurement crosses its preregistered threshold for
use as a positive project or resume claim. The three states are recorded
separately, but positive eligibility implies both Ship Completeness and
Measurement Validity.

**Evolver** (`pico/evolver/`):
The opt-in Beta subsystem exposed through `pico evolve`. It reuses the existing
benchmark-driven loop to diagnose trajectories, propose Candidate Patches, evaluate
them against deterministic and sealed gates, and record reviewable evidence. It does
not activate a candidate merely because the candidate was generated or promoted.
_Avoid_: "self-updater" -- Evolver produces evidence and candidate commits, not an
automatic replacement for the running Runtime.

**Evolution Run**:
One durable Evolver execution identified by a run-spec YAML and its external
`work_dir`. `pico evolve run` starts it or resumes the journal already stored under
that directory; `status` reconstructs progress from artifacts, and `finalize` ends
the run and unseals its test result. Promotion selects the next baseline inside the
run. Candidate activation remains a separate manual review step.
_Avoid_: "campaign" or "resume command" -- there is one resumable `run` command.

**Candidate Manifest**:
The canonical, deterministic metadata view over one existing `AppliedPatch` and
its target files. It records a Candidate Label, `PatchWhere`, target-file list,
raw before/after content hashes, patch digest, evaluator fixture, evaluator, and
activation policy. It does not
introduce another mutation engine. G5 validates the Manifest against the patch
before the child commit is created.

**Candidate Label**:
One review label in the Candidate Manifest. The six public labels map to current
`PatchWhere` behavior as follows:

| Label | `PatchWhere` mapping | Current G5 behavior |
|---|---|---|
| `skill` | `skill` | Schema-recognized but fails G5 because no deterministic retained-Runtime Skill routing fixture and evaluator are wired. |
| `prompt` | `system_prompt_template`, `task_wrapper_prompt` | Schema-recognized but fails G5 because no deterministic retained-Runtime prompt rendering fixture and evaluator are wired. |
| `policy` | `config`, `hook_new`, `hook_modify` | Schema-recognized but fails G5 because no deterministic retained-Runtime policy evaluator is wired. |
| `runtime` | `tool_description`, `hook_new`, `hook_modify`, `tool_new`, `loop_override`, `context_override`, `tool_override` | The only currently supported label, limited to the AppWorld Runtime fixture surface (`benchmarks/appworld/agent_cli.py` and `benchmarks/appworld/tool.py`); uses the executable Focused-Fisher three-shield train evaluator and requires human review. |
| `model_profile` | `config` | Schema-recognized but fails G5 until a config-only fixture and evaluator exist; model-weight files are always forbidden. |
| `route` | `config` | Schema-recognized but fails G5 until a config-only fixture and evaluator exist; model-weight files are always forbidden. |

_Avoid_: "candidate type" -- labels classify the same Candidate Patch mechanism;
unsupported labels remain reviewable proposals but cannot pass G5.
Labels are bound from the changed artifact surface, not inferred from the
author's intent. For example, changing the embedded `APPWORLD_PROMPT` string in
`benchmarks/appworld/agent_cli.py` is a `runtime` candidate because that file is
part of the supported Runtime fixture; it does not become a supported `prompt`
candidate by self-declaration.

**Manifest Gate**:
G5, the pre-commit fail-closed check that binds a Candidate Manifest to the exact
Candidate Patch. It rejects digest or target drift, unsupported labels, paths
outside the label allowlist, unsafe or symlinked paths, sealed tests, scorers,
gate math, evidence ledgers, and the Evolver kernel.

**Evidence Verdict**:
The durable outcome of candidate evaluation: `accepted`, `rejected`, `failed`,
or `inconclusive`. Only a fully measured, non-regressing `accepted` outcome may
count as improvement or promotion. Provider and infrastructure failures are
`failed`; missing, zero-attempt, or fewer-than-requested-K measurements are
`inconclusive`.

**Candidate Promotion**:
Selection of an accepted candidate as an Evolution Run baseline. Promotion is
train-side navigation inside the run and does not activate the candidate in the
live Runtime.

**Activation Bundle**:
The canonical artifact directory under
`<work_dir>/activation/<candidate_id>/`. It contains the Candidate Manifest,
Evidence Verdict, before and after snapshots, a Rollback Artifact, and the
activation state. A runtime candidate always starts `pending_human`; the state
record never edits the caller's Git checkout or moves `HEAD`. The bundle binds
the snapshots to the exact parent and candidate commits. Held-out sealed results
remain excluded from automated promotion; a human can review the unsealed
retention report before approving activation.

**Rollback Artifact**:
The digest-verified snapshot matching the Activation Bundle's `before` state.
It remains available after approval or activation state changes so a human can
restore the reviewed pre-candidate state.

### Release Evidence

**Release Layer**:
One Gate or audit that `scripts/verify_release.py` runs and records as a unit
(`LAYERS`): the retained suite, the TUI bundle, V-P0, the host gate, V-LP,
V-C0/V-S0, V-LF, the installed Memory-composition layer, V-TE0, V-E0, the
dependency audit, the asset gate, and the small
real Evolution Run. Each layer carries its commands, deciding exit code, hashed log,
imported or produced sub-report, and one of the evidence classes `deterministic`,
`package`, `live`, or `audit`.
_Avoid_: calling a layer a step -- layers run in dependency order and each one owns a
separate result, so a later layer never inherits an earlier layer's status.

**Release Evidence Report**:
The V-R0 artifact written by `scripts/verify_release.py` to
`.pico/evidence/release/release-report.json` (schema `pico.release.evidence.v1`): every
Release Layer record, the commit the run is bound to, and the named gaps. Its status is
`passed` only when the run selected every layer, named no gap, and every layer passed.
_Avoid_: treating it as a build artifact index -- it records which Gates passed together
at one commit, not what a release ships.

**Named Gap**:
One machine-readable entry in the Release Evidence Report's `gaps` list, carrying the
layer, the gap name, and a detail string. Unselected layers, absent live credentials, an
absent V-P0 handoff, absent Evolution Run inputs, an unbindable sub-report, and a dirty
checkout all become gaps.
_Avoid_: "skip" -- a V-R0 layer that measured nothing is still reported with its own
status and a gap, never omitted.

### Workspace & Onboarding

**Workspace**:
The filesystem tree the Agent operates on. Foreground Hosts (`pico` and
`pico run`) use the current directory when no Workspace override is configured;
Gateway and configured invocations use their fixed Workspace. Exactly one per
running agent.
_Avoid_: confusing the Workspace (the live instance) with the Workspace Template it is seeded from.

**Workspace State**:
The Pico-owned mutable state associated with a Workspace: Sessions, Memory,
Local Skills, bootstrap files, and evidence. Project-local foreground
invocations store it under `~/.pico/projects/<project-id>`; explicit
`--workspace`, a non-default configured Workspace, and Gateway preserve the v1
colocated layout.
_Avoid_: treating Workspace State as the Agent's tool working directory.

**Pico State**:
Persistent data owned by the Pico product. Global configuration and Runtime
data default to `~/.pico`, and project-local Workspace State to
`~/.pico/projects/<project-id>`. Myna owns its repository binding and runtime root,
selected by explicit `myna init`. `PICO_HOME` may relocate the global Pico
root. Pico does not import external product state implicitly; an explicit
`--config` or `--workspace` path is direct operation on that location, not a
migration protocol.

**Workspace Template** (`templates/`):
The bundled markdown seed files copied into Workspace State on first run by
`sync_workspace_templates()` (idempotent — fills only missing files, so user edits win):
`SOUL.md` (agent persona), `AGENTS.md` (agent operating instructions), `USER.md` (user
profile), `TOOLS.md` (tool-usage notes), and `memory/MEMORY.md` (legacy memory seed).
On the L4 layout these map
under `agent_memory/profile/` (soul.md, agent.md) and `user_memory/profile/` (user.md);
`TOOLS.md` stays at the Workspace State root.

**Onboarding** (`pico onboard` → `run_wizard`):
The first-run wizard (LLM provider -> sandbox -> channel -> Myna or
Memory-off) that also seeds Workspace State via `sync_workspace_templates()` and
can complete a first Runtime Turn; gated at startup by
`ensure_configured_or_onboard()`. Myna selection requires the operator to run
`myna init` in the target Git repository.

**Bootstrap Files**:
The identity files concatenated into every prompt — `soul.md` + `agent.md` + `TOOLS.md` —
rendered by the Context Builder / bootstrap segment.
_Avoid_: lumping `user.md` in — the user profile enters via the `# Memory` segment, not bootstrap.
