# Context

## Glossary

### Local code-agent runtime

Pico's product core: a local runtime for executing coding-agent work against a
workspace. CLI, desktop, and headless evaluation are entrypoint adapters over the
same runtime, not separate products.

### Headless evaluation lab

The built-in non-UI evaluation surface for running tasks, verifiers, runtime
policy A/B tests, and prompt optimization against the shared local code-agent
runtime.

### RuntimeEvent

The canonical runtime fact emitted by Pico's execution kernel and the source of
truth for the whole product, not just evaluation. Model chunks, tool calls, tool
results, permission events, artifact writes, token usage, terminal statuses, and
recovery events are recorded as runtime events first. CLI output, desktop
timelines, session history, trace files, reports, telemetry, and task exports are
projections from runtime events.

### Session history

A user-visible conversation projection derived from runtime events. Session
history is not Pico's source of truth and should not be used as the primary
database for runtime recovery, evaluation, reporting, prompt optimization, or
model-history construction.

### ModelHistoryProjector

The policy layer that turns runtime events into the next model input. It decides
which user, model, tool, permission, artifact, and diagnostic facts are exposed to
the model, instead of rebuilding prompts directly from session history.

### ProjectionManager

The runtime boundary that derives user-visible and machine-readable artifacts
from runtime events. CLI output, session views, traces, reports, task exports,
artifact manifests, and redaction should be coordinated here instead of being
assembled separately by entrypoint adapters. It is not the authority for runtime
execution, verifier execution, task-run WAL, or provider normalization. CLI and
headless evaluation should consume the same projection/capture boundary. Runtime
projection helpers belong with this boundary, not inside the kernel runner
module; legacy imports may be re-exported during migration.

### RuntimeArtifactSet

The capture result for one runtime invocation. It identifies the run and the
artifacts derived from its runtime events, including runtime-event ledger, trace,
report, manifest, session projection, export projection, and projection
diagnostics. It is a read-model result, not a separate source of truth. Artifact
paths are owned by `RunStore`; projection/capture code should coordinate writes
through that store instead of inventing paths.

### Runtime artifact manifest

The stable contract that names the files and projections captured for one
runtime invocation. It records schema version, run id, terminal status, artifact
paths, session/export projections, and projection diagnostics so CLI, headless
evaluation, and inspection code can agree on what was produced. The first slice
captures session/export projection snapshots in the manifest without requiring
every inspection path to read from the manifest immediately.

### Projection diagnostic

A machine-readable warning or error produced while deriving read models from
runtime events. Storage and redaction failures are capture failures; unsupported
event shapes, missing terminal status, and incomplete read-model facts should be
visible diagnostics unless they make the artifact contract unsafe to trust.

### RuntimeEvent v2

The future schema-aligned runtime event contract with explicit identity,
role/author/status, content, actions, and projection refs. It should not block
the first ProjectionManager slice; the first slice should adapt Pico's current
`type`, `payload`, and `created_at` events and surface schema gaps as projection
diagnostics.

RuntimeEvent v2 is the canonical event envelope for new runtime output, not a
rename of the old event shape. It promotes shared runtime identity and ordering
facts such as schema version, event id, invocation id, sequence, kind, status,
actor, and created time into the envelope. Kind-specific data remains in payload.
Legacy `type`, `payload`, and `created_at` events are compatibility input during
migration, but they are not the target output contract for new runtime code.

In RuntimeEvent v2, `kind` names the fact that happened, `status` names the
outcome of that fact, and `actor` names the runtime boundary that produced it.
Kinds should stay stable, such as `model_output`, `tool_result`, and
`terminal_status`; outcomes such as `ok`, `denied`, `requires_decision`,
`malformed`, `timeout`, and `failed` belong in status instead of being encoded
into separate kind names.

The runtime event ledger is the sequence authority for RuntimeEvent v2. Sequence
numbers are assigned at append time, increase within one invocation, and are not
provided by callers. Projections and replay should order v2 events by invocation
id and sequence. Legacy events without sequence may be adapted in read order
during migration, but that ordering is compatibility behavior rather than native
v2 evidence.

`invocation_id` identifies one runtime invocation, such as one CLI request or
one kernel-backed headless runtime run. It is not a model call id. Provider
requests within an invocation should use `model_call_id`; tool requests should
use `tool_call_id`; headless task attempts should use `task_run_id` outside the
runtime invocation and reference the runtime invocation; individual runtime facts
should use `event_id`.

`terminal_status` remains a RuntimeEvent kind in v2. The envelope status field
describes the outcome of one event, while the terminal status event closes the
whole invocation and is the authority for invocation status in manifests,
reports, CLI inspection, and headless exports. Projections should not infer run
completion from the last event's status.

RuntimeEvent v2 does not define a generic top-level content field. The envelope
contains shared identity, ordering, routing, status, actor, and timestamp facts.
Kind-specific data such as user text, model text, tool args, tool content,
provider metadata, errors, and artifact refs belongs in payload. User-visible
timeline content is a projection concern, not runtime truth.

The first RuntimeEvent v2 slice enforces the envelope strictly and treats most
payload schemas as soft contracts. Missing or incomplete payload facts should
become projection diagnostics unless they make the invocation close event or
artifact contract unsafe to trust. `terminal_status` is the key hard payload
contract because manifests, reports, CLI inspection, and headless exports depend
on it for invocation outcome.

RuntimeEvent v2 is the write format for new kernel runs. Legacy runtime event
artifacts may be read through a compatibility adapter, but inspection and
projection must not silently rewrite historical `runtime_events.jsonl` files.
Any historical artifact migration should be an explicit migration command rather
than a side effect of reading or inspecting a run.

RuntimeEvent v2 may carry kind-specific `artifact_refs` in payload when a runtime
fact needs to reference large or externalized raw evidence, such as full tool
output. The v2 envelope should not carry generic projection refs. Projection
artifacts such as trace, report, session/export snapshots, and manifest paths
belong to ProjectionManager and the runtime artifact manifest, not to individual
runtime facts.

RuntimeEvent v2 may reserve optional causality and correlation fields, such as
`parent_event_id` and `correlation_id`, for future streaming, parallel tools,
subagents, and lifecycle grouping. The first v2 implementation does not expand
Pico's execution model: one invocation still has one ledger sequence and the
kernel runner remains serial. Reserved correlation fields should be captured and
projected when present, but they should not imply concurrent execution in the
first slice.

Provider metadata belongs on model boundary events such as `model_output` and
`model_failure`, not on the invocation envelope or as copied terminal status
fields. Reports may aggregate provider, model, finish reason, usage, and failure
facts from model events, but terminal status should remain the invocation close
event rather than a duplicated provider summary.

The first RuntimeEvent v2 implementation should use one event dataclass plus
ledger builders and validators rather than a class hierarchy per event kind.
Kind-specific payload schemas can harden over time through validators and
projection diagnostics without changing the shared envelope contract.

RuntimeEvent v2 actors are a small controlled vocabulary for new writes:
`runtime_runner`, `model_adapter`, `agent_flow`, `tool_runtime`,
`permission_policy`, `projection_manager`, and `headless_lab`. New runtime code
should not invent actor aliases. Legacy or future unknown actors may be read
compatibly and surfaced as diagnostics instead of crashing inspection.

RuntimeEvent v2 statuses are a small controlled vocabulary for new writes:
`started`, `completed`, `ok`, `failed`, `error`, `denied`,
`requires_decision`, `skipped`, and `unknown`. Status names should describe the
generic outcome of an event. Specific failure taxonomies such as
`provider_network_error`, `permission_denied`, or `runtime_artifact_capture_failed`
belong in payload fields such as `failure_classification`.

The first RuntimeEvent v2 kind vocabulary covers the current kernel spine:
`invocation_start`, `user_input`, `model_output`, `model_failure`,
`tool_call_requested`, `tool_permission_decision`, `tool_argument_validation`,
`tool_result`, `final_answer`, and `terminal_status`. New runtime writes should
use this controlled vocabulary until a later feature slice deliberately extends
it. Legacy or future unknown kinds may remain visible in trace projections with
diagnostics, but read-model projections are not required to understand them.

RuntimeEvent schema version and runtime artifact manifest schema version are
separate contracts. Moving `runtime_events.jsonl` to RuntimeEvent v2 should add
explicit event-schema metadata to the manifest, but it should not bump the
manifest schema version unless the manifest structure itself changes.

The first RuntimeEvent v2 projection migration should make trace output
v2-native because trace is the closest read model to the runtime ledger. Report,
session, and export projections should keep their external contracts stable
while deriving their facts from v2 events internally.

Headless task WAL remains a task-run lifecycle ledger, not a duplicate runtime
event ledger. It should reference the runtime invocation id, runtime manifest,
and runtime event schema version when a kernel run finishes. It should not copy
model, tool, permission, final-answer, or terminal runtime events into the
headless WAL.

The RuntimeEvent v2 implementation batch should cover event schema, ledger
compatibility, kernel emission, projection compatibility, manifest event-schema
metadata, CLI inspection, headless runtime references, and fake/live acceptance
gates. ModelHistoryProjector policy over v2 events is the next batch after the
v2 ledger and projection contracts stabilize.

RuntimeEvent v2 acceptance has two layers. Fake-provider tests are the
deterministic gate for envelope validation, sequence assignment, projection
compatibility, manifest metadata, CLI inspection, and headless references.
Live-provider acceptance is required at the end of the batch for no-tool and
read-only-tool kernel runs, proving real provider metadata and runtime artifacts
flow through the v2 event contract.

RuntimeEvent v2 should not be bundled with a broad runtime package migration.
The implementation may introduce a narrow `pico/runtime_events.py` module for
event types, validators, adapters, and serialization, with `runtime_kernel.py`
re-exporting compatibility symbols as needed. It should not turn the whole
kernel into a `pico/runtime/` package in the same batch.

Kernel release-candidate validation should require RuntimeEvent v2 artifacts
after the v2 producer, projection, and headless reference paths are in place.
The gate should reject manifests without runtime event schema metadata or with
runtime ledgers that fail v2 envelope validation. This belongs at the end of the
v2 batch, not in the first event-model issue.

### ModelAdapter

The provider normalization boundary. It turns a Pico model request into a
provider call and returns a normalized model result with text, usage,
finish-reason, raw metadata, and classified provider errors. The first runtime
replacement should make this boundary robust while still using text input/output;
provider-native tool calling is a later flow concern, not the first provider
hardening target.

### ToolRuntime

The complete lifecycle boundary for model-requested tools. It validates
arguments, checks tool availability, evaluates permissions, parks permission
requests when needed, executes the tool, captures output, writes large artifacts,
redacts secrets, classifies tool failures, emits tool and permission runtime
events, records telemetry, and returns a normalized tool result to the agent flow.

### Permission event

A runtime fact, not a UI-only behavior. The runtime records permission requests,
permission decisions, and denied-tool results as runtime events. CLI, desktop,
and headless evaluation present or resolve those facts differently, but they do
not own separate permission semantics.

### Headless eval trust posture

Headless evaluation treats the config and agent under test as untrusted by
default. Eval runs should fail closed unless they have an explicit throwaway
workspace, protected verifier boundary, secret/environment allowlist, tool
permission policy, and provider configuration. Infrastructure failures are
separate from benchmark failures.

### Official verifier

The independent authority for benchmark success. A model self-check or final
answer is only a semantic assertion by the agent, not a benchmark pass. Reports
must distinguish semantic status, runtime status, and official verifier result.

### Heavy-task live surface

The small model-visible progress surface for long tasks. It should stay thin:
inventory, todo, and public self-check. The model should do engineering work;
Pico should automatically capture compact evidence such as tool summaries,
artifact hashes, public command results, changed-file metadata, and verifier
output.

### Runtime rollout switch

The compatibility surface for replacing Pico's runtime. The codebase can be
rebuilt aggressively, but user-visible behavior should keep a way to run or
compare the legacy runtime and the new kernel runtime until the kernel covers
one-shot, REPL, and headless task runs.

### Projection rollout boundary

The first ProjectionManager slice applies to the new kernel runtime path and
kernel-backed headless evaluation only. Legacy `pico/runtime.py` trace, report,
session, and memory behavior remains a compatibility path until the kernel
runtime replaces it deliberately.

### Runtime spine slice

An implementation slice that moves one thin path through the full runtime spine
instead of completing one horizontal layer in isolation. Early work should prefer
end-to-end slices such as "one-shot run emits runtime events and projects CLI
output" over standalone event, storage, CLI, or tool rewrites that cannot run.

### Runtime acceptance gates

Runtime replacement work has two acceptance layers. Fake-provider tests are the
automated regression gate for CI and fast local checks. Live-provider runs are
the real acceptance gate for proving the agent path works with a real model,
normalized provider metadata, runtime events, and report artifacts.

### Projection acceptance gates

Projection/capture work has two acceptance layers. Fake-provider tests are the
automated regression gate for manifest contracts, projection diagnostics, and
shared CLI/headless capture behavior. Live-provider runs are the real acceptance
gate for proving the same artifact contract with a real model and provider
metadata.

### First runtime slice

The first runtime replacement slice must include both a no-tool final-answer
case and a single safe read-only tool case. The no-tool case proves
`RuntimeRunner`, `ModelAdapter`, and projections. The read-only tool case proves
agent-flow parsing, `ToolRuntime`, runtime events, model-history projection, and
finalization without requiring write or shell permissions.

### First tool surface

The first runtime replacement should expose only the minimum read-only code-agent
tool surface: read file, list files, and search text. Write, edit, shell,
subagents, memory, plan mode, todos, desktop permission UI, and prompt
optimization are later slices.

### Advanced context and memory policies

Context compaction, durable memory, retrieval, long-session handoff, and similar
advanced policies are later Maka-style runtime policies. They are not first-slice
requirements and should not be migrated from v3 as a starting assumption.

### Maka-aligned runtime terminology

Pico should keep Maka-aligned architecture terms for the shared concepts:
`RuntimeRunner`, `InvocationContext`, `AgentFlow`, `ToolRuntime`,
`ModelAdapter`, `RuntimeEvent`, `RuntimeEventLedger`, `ProjectionManager`,
`HeadlessLab`, `TaskRunStore`, `AcceptancePolicy`, and `RuntimePolicyAB`. Python
module names can use snake_case, but the concept names should remain directly
traceable to Maka's design.

### Runtime package boundary

The target runtime kernel boundary is a dedicated runtime package under Pico,
and headless evaluation capabilities should live under `pico/headless`. On
`main`, `pico/runtime.py` already exists as the legacy runtime module, so the
first kernel slice may use a narrow transitional module such as
`pico/runtime_kernel.py` instead of forcing a broad package migration. The CLI
remains an adapter under `pico/cli.py`. The new kernel should not be mixed into
the legacy `pico/core` module layout.

### Legacy core

The existing `pico/core` layout is legacy once the Maka-style runtime rewrite
begins. It may remain as a compatibility adapter during rollout, but new runtime
features should land in `pico/runtime` or `pico/headless`, not in `pico/core`.

### Kernel default switch

The new kernel runtime should run beside the legacy runtime until it passes both
fake-provider tests and live-provider acceptance for a no-tool final-answer case,
a read-only tool case, runtime-event-driven projections, normalized provider
metadata, and a headless single-task run. Only then should `pico` default to the
kernel runtime, with legacy kept temporarily as an explicit fallback.

### Projection follow-up sequence

After the first ProjectionManager and runtime artifact manifest slice, the next
runtime work should prioritize RuntimeEvent v2 schema alignment before desktop
or broader tool expansion. The intended order is ProjectionManager, RuntimeEvent
v2, ModelHistoryProjector over v2 events, expanded ToolRuntime permissions and
write/shell tools, then desktop/session UI.
