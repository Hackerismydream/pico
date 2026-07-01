# PRD: RuntimeEvent v2 Envelope and Ledger Migration

## Problem Statement

Pico's Maka-style runtime rebuild depends on runtime events being the product
truth for CLI output, session projections, traces, reports, headless exports,
and future desktop views. The current kernel path has proven the vertical runtime
spine, ProjectionManager capture, runtime artifact manifest, CLI inspection, and
headless task integration, but its event shape is still too weak: shared runtime
identity, ordering, actor ownership, and event outcome are scattered through
ad-hoc payload fields or inferred by readers.

This makes the next layers risky. Model-history projection, richer tool
permissions, provider diagnostics, headless acceptance gates, release-candidate
validation, and future desktop timelines all need a stable event contract. Pico
needs RuntimeEvent v2 before it expands the runtime surface further.

## Solution

Pico will introduce RuntimeEvent v2 as the canonical write format for new kernel
runtime events. RuntimeEvent v2 is a strict shared envelope with schema version,
event id, invocation id, sequence, kind, status, actor, created time, optional
causality/correlation fields, and kind-specific payload.

New kernel runs will write v2 events. Legacy `type`, `payload`, and `created_at`
events remain compatibility input during migration, so old artifacts can still
be inspected and projected without being silently rewritten. ProjectionManager
will consume v2 events, write v2-native traces, keep report/session/export
contracts stable, and add runtime event schema metadata to the manifest without
bumping the manifest schema version.

Headless task WAL will continue to describe task-run lifecycle and reference the
runtime invocation/artifacts instead of duplicating the runtime ledger. Release
candidate validation will require v2 runtime artifacts at the end of the batch.

## User Stories

1. As a Pico user, I want new kernel runs to produce stable runtime events, so that CLI inspection and reports are based on one reliable runtime truth.
2. As a Pico user, I want existing runtime artifacts to remain inspectable, so that old runs are not made unreadable by the migration.
3. As a Pico user, I want run status to come from an explicit terminal event, so that Pico does not guess completion from the last event.
4. As a Pico user, I want trace output to show event identity, ordering, status, and actor, so that runtime failures are easier to inspect.
5. As a Pico user, I want reports to preserve their external shape, so that event-schema migration does not break report consumers unnecessarily.
6. As a Pico user, I want session/export projections to stay stable, so that the runtime upgrade does not change user-facing behavior without need.
7. As a Pico user, I want provider metadata captured on model events, so that live runs show which provider/model/finish reason/usage path was used.
8. As a Pico user, I want tool results and permission outcomes to remain visible, so that read-only tool behavior is auditable after the migration.
9. As a Pico maintainer, I want `RuntimeEventLedger` to assign event sequence numbers, so that callers cannot create conflicting order.
10. As a Pico maintainer, I want `invocation_id` to identify one runtime run, so that model calls, tool calls, and terminal status stay linked.
11. As a Pico maintainer, I want `model_call_id` and `tool_call_id` to remain child identifiers, so that provider and tool lifecycles can be correlated within one invocation.
12. As a Pico maintainer, I want event `kind`, `status`, and `actor` to have distinct meanings, so that projections and diagnostics do not infer semantics from overloaded strings.
13. As a Pico maintainer, I want kind/status/actor controlled vocabularies for new writes, so that runtime facts do not drift into aliases.
14. As a Pico maintainer, I want unknown legacy or future event shapes to become diagnostics instead of hard crashes, so that inspection remains robust.
15. As a Pico maintainer, I want strict envelope validation and soft first-pass payload validation, so that the migration is safe without becoming a full repo schema rewrite.
16. As a Pico maintainer, I want `terminal_status` to remain a first-class event kind, so that manifests and headless exports have one close event authority.
17. As a Pico maintainer, I want runtime event schema version separated from artifact manifest schema version, so that manifest consumers are not forced into fake breaking changes.
18. As a Pico maintainer, I want trace output to be v2-native, so that trace remains the closest read model to the runtime ledger.
19. As a Pico maintainer, I want report/session/export projections to be v2-backed, so that read models consume the canonical event contract.
20. As a Pico maintainer, I want historical `runtime_events.jsonl` files left untouched during inspection, so that artifacts remain evidence rather than mutable cache.
21. As a Pico maintainer, I want payload-level `artifact_refs` for large raw evidence, so that runtime facts can reference externalized tool output without knowing projection paths.
22. As a Pico maintainer, I want projection artifact paths owned by ProjectionManager and the manifest, so that individual runtime events do not depend on report/trace/session file layout.
23. As a Pico maintainer, I want optional causality and correlation fields reserved, so that future streaming, parallel tools, and subagents have a path without changing the core envelope.
24. As a Pico maintainer, I want the first implementation to preserve serial runner semantics, so that RuntimeEvent v2 does not expand execution behavior prematurely.
25. As a Pico maintainer, I want a narrow runtime events module if needed, so that event types can be isolated without migrating the whole runtime kernel package.
26. As a Pico maintainer, I want release-candidate validation to reject missing v2 event metadata after the migration, so that kernel default gates depend on the new truth contract.
27. As a Pico maintainer, I want fake-provider tests for every contract, so that CI can validate v2 without real network calls.
28. As a Pico maintainer, I want live-provider acceptance at the end of the batch, so that real provider metadata and artifacts are proven against the v2 contract.
29. As a headless lab user, I want task WAL events to reference runtime invocation artifacts, so that evaluation orchestration does not duplicate runtime facts.
30. As a future desktop user, I want event ids, actors, statuses, and sequences preserved, so that desktop timelines can be projected from the same ledger later.
31. As a future contributor, I want ADR-backed event terminology, so that implementation decisions remain understandable during later runtime slices.
32. As a resume reviewer, I want Pico's runtime event contract to be explicit and tested, so that the project can be explained as agent infrastructure rather than a CLI demo.

## Implementation Decisions

- RuntimeEvent v2 is the canonical write format for new kernel runtime output.
- Legacy events are compatibility input only. They may be adapted in memory for reads, inspection, and projection, but they are not the new output target.
- The v2 envelope contains schema version, event id, invocation id, sequence, kind, status, actor, created time, optional parent event id, optional correlation id, and payload.
- `kind` names the fact, `status` names that fact's outcome, and `actor` names the runtime boundary that produced it.
- `RuntimeEventLedger` is the sequence authority. Callers do not provide sequence numbers.
- `invocation_id` identifies one runtime invocation, not a model call. Provider calls and tool calls use child identifiers.
- `terminal_status` remains a v2 event kind and is the invocation close authority.
- The envelope has no generic top-level content field. Kind-specific content remains in payload.
- The first v2 slice enforces the envelope strictly and treats most payload schemas as soft contracts.
- `terminal_status` is the hard payload contract because manifests, reports, CLI inspection, and headless exports depend on it.
- New writes use a controlled kind vocabulary for the current kernel spine: invocation start, user input, model output, model failure, tool request, permission decision, argument validation, tool result, final answer, and terminal status.
- New writes use a controlled actor vocabulary for the current runtime boundaries: runtime runner, model adapter, agent flow, tool runtime, permission policy, projection manager, and headless lab.
- New writes use a small status vocabulary. Specific failure classifications remain payload facts.
- Provider metadata belongs on model boundary events, not terminal status or the invocation envelope.
- Runtime events may carry payload-level artifact references for large raw evidence.
- Runtime events do not carry generic projection references. Projection artifacts remain owned by ProjectionManager and the manifest.
- RuntimeEvent schema version and runtime artifact manifest schema version are separate contracts.
- The manifest should declare the runtime event schema version without bumping the manifest schema version unless the manifest structure changes.
- Trace output should become v2-native.
- Report, session, and export projections should keep their external contracts stable while deriving facts from v2 internally.
- Headless task WAL remains task-run lifecycle truth and references runtime invocation artifacts instead of copying model/tool/final runtime events.
- The implementation may introduce a narrow runtime-events module for types, validation, adapters, and serialization.
- This batch must not migrate the whole runtime kernel into a package.
- This batch must not change ModelHistoryProjector policy. ModelHistoryProjector over v2 is the next batch after v2 ledger and projections stabilize.
- Kernel release-candidate validation should require v2 runtime artifacts at the end of the batch.

## Testing Decisions

- The highest test seam is the kernel runtime artifact contract: a run should emit a v2 runtime ledger, v2-native trace, stable report/session/export projections, and manifest event-schema metadata.
- Existing fake-provider kernel tests should prove no-tool and read-only-tool v2 event emission without network calls.
- Existing ProjectionManager tests should prove v2 consumption, legacy event compatibility, diagnostics, redaction, trace output, and manifest metadata.
- Existing CLI inspection tests should prove v2 and legacy artifacts remain inspectable.
- Existing headless task tests should prove task WAL/export references runtime invocation artifacts and event schema version without duplicating the runtime ledger.
- Existing release-candidate gate tests should prove v2 artifacts are required once the v2 batch is complete.
- Tests should assert externally visible artifact contracts rather than private helper implementation.
- Fake-provider tests are the deterministic gate for CI and local issue work.
- Live-provider acceptance is required at the end of the batch for one no-tool kernel run and one read-only-tool kernel run.
- Live-provider acceptance must verify provider metadata, terminal status, manifest metadata, runtime events, trace/report artifacts, and headless compatibility where applicable.
- Historical legacy event fixtures should be used to prove compatibility adapters do not silently rewrite old artifacts.

## Out of Scope

- Rewriting the whole runtime kernel into a package.
- Replacing the legacy runtime path.
- Changing ModelHistoryProjector prompt policy over v2 events.
- Adding provider-native tool calling.
- Adding write, edit, shell, subagent, memory, plan, or todo tools.
- Adding concurrent execution, parallel tool calls, streaming model chunks, or subagents.
- Building desktop UI or desktop timeline projections.
- Bumping the runtime artifact manifest schema solely because event schema changes.
- Silently rewriting historical `runtime_events.jsonl` files during inspection.
- Making every kind-specific payload schema fully strict in the first slice.
- Treating model self-checks as official headless verifier results.

## Further Notes

- This PRD follows ADR 0001's Maka-style runtime kernel direction.
- This PRD is codified by ADR 0002, which accepts RuntimeEvent v2 envelopes for kernel runtime facts.
- The intended implementation order is event model and ledger compatibility, kernel v2 emission, ProjectionManager v2 consumption, CLI/headless references, and final acceptance gates.
- The next major batch after this PRD is ModelHistoryProjector policy over v2 events.
