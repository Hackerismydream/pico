# ADR 0002: Adopt RuntimeEvent v2 Envelope for Kernel Runtime Facts

## Status

Accepted

## Context

Pico's Maka-style runtime direction depends on runtime events being the product
truth for CLI output, session views, traces, reports, headless exports, and
future desktop projections. The first kernel slices proved this shape with a
minimal `type`, `payload`, and `created_at` event structure, but that shape keeps
shared runtime identity, ordering, actor ownership, and event outcome inside
ad-hoc payload fields.

The ProjectionManager and runtime artifact manifest are now stable enough to
capture runtime facts consistently. The next runtime slice needs a stronger
event envelope without breaking legacy artifacts or turning the migration into a
full prompt-policy rewrite.

## Decision

New kernel runtime writes will use RuntimeEvent v2 envelopes. A v2 event has a
strict shared envelope with schema version, event id, invocation id, sequence,
kind, status, actor, created time, optional causality/correlation fields, and a
kind-specific payload.

Pico will keep legacy `type`, `payload`, and `created_at` events as
compatibility input during migration, but they are no longer the target output
contract for new runtime code. Legacy artifacts may be adapted in memory for
inspection and projection; reading a historical run must not silently rewrite
its `runtime_events.jsonl`.

The v2 envelope is strict, while most kind-specific payload schemas remain soft
contracts in the first slice. Missing payload facts should become projection
diagnostics unless they make the invocation close event or artifact contract
unsafe to trust. `terminal_status` remains a first-class event kind and is the
authority for invocation outcome.

RuntimeEvent schema version and runtime artifact manifest schema version remain
separate contracts. Moving `runtime_events.jsonl` to v2 adds event-schema
metadata to the manifest but does not bump the manifest schema unless the
manifest structure itself changes.

## Alternatives Considered

### Rewrite all existing events directly

Rejected. This would turn the v2 work into a broad repository migration and
would disrupt the ProjectionManager, CLI inspection, headless exports, and tests
that were just stabilized. Compatibility adapters keep the migration reviewable.

### Strict payload classes for every event kind

Rejected for the first slice. Per-kind classes may become useful later, but the
immediate need is a stable ledger envelope, ordering, actor ownership, and
projection compatibility. A single event dataclass with builders and validators
keeps the first implementation smaller.

### Bump the runtime artifact manifest schema

Rejected. The manifest structure is not changing just because the event ledger
format changes. The manifest should declare the runtime event schema version
instead of pretending the artifact manifest itself had a breaking change.

### Remove `terminal_status`

Rejected. The envelope `status` describes one event's outcome, not the whole
invocation. Manifests, reports, CLI inspection, and headless exports need an
explicit invocation close event instead of inferring completion from the final
event in the ledger.

## Consequences

- `RuntimeEventLedger` becomes the sequence authority for v2 events.
- New runtime writes use controlled vocabularies for kind, status, and actor.
- Trace output should become v2-native because it is closest to the ledger.
- Report, session, and export projections should keep their external contracts
  stable while deriving facts from v2 events.
- Headless task WAL remains a task-run lifecycle ledger and references runtime
  invocation artifacts instead of duplicating the runtime event ledger.
- ModelHistoryProjector policy over v2 events is a follow-up batch, not part of
  the first v2 ledger/projection migration.
