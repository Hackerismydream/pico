# CodeCairn Memory replacement delivery analysis

> **Status: Pico-side `codecairn-001` and `codecairn-002` implementation
> complete under Issue #65; joint `codecairn-003` evidence complete under
> Issue #70.** Current `main` selects CodeCairn and no longer bundles EverOS.
> "v0.2" below names the Pico Harness engineering/product milestone, not
> package semver.

## Decision

Replace Pico's bundled EverOS Memory integration with the installed CodeCairn
Memory Adapter defined in
[the backend contract](../../specs/codecairn-memory-backend.md).

The chosen relationship is:

```text
Pico Runtime
  -> MemoryBackend Interface
     -> installed CodeCairn Adapter
        -> CodeCairnApplication
```

This is deeper than an MCP sidecar and narrower than merging the repositories.
Pico keeps one existing Interface. CodeCairn hides source capture, durable
import, repository identity, ranking, packing, and storage behind one Adapter.

## Pre-implementation reality and target

The table below preserves the state used to make the replacement decision. It
does not describe the post-delivery Runtime.

| Area | Pico before delivery | Replacement target |
| --- | --- | --- |
| Default Memory | bundled EverOS Plugin, direct dependency, default backend `everos` | base distribution installs a compatible CodeCairn build and selects its contribution |
| Recall | user track plus EverOS Agent/Skill track | user track maps to repository recall; Agent track becomes empty |
| Store | one turn slice after Session save | durable CodeCairn Source Journal and importer |
| Skills | Local BM25 plus EverOS remembered Skills and weighted RRF | preserve Local Skills; remove EverOS source and stale fusion controls |
| Onboarding | creates and edits EverOS configuration | require explicit `codecairn init`, validate, and explain remediation |
| Packaging | EverOS bundled with Pico | install compatible CodeCairn distribution and discover entry point |
| Continuity | historical EverOS V-O0 | CodeCairn cross-process and cross-repository Gates |
| Evaluation | EverOS PicoBench evidence | new `null` versus `codecairn` experiment identity |

The existing `MemoryBackend` Interface is sufficient for v0.2 recall,
store, lifecycle, and no-op feedback. It does not carry a stable persisted
Memory batch id. The first CodeCairn Adapter therefore guarantees idempotent
journal-prefix replay under Pico's current one-store-call-per-persisted
after-Turn-slice contract. Arbitrary duplicate caller writes remain a future
Interface change.

## Alternatives rejected

### Keep EverOS and add CodeCairn as another optional backend

This minimizes deletion but leaves two product stories, two onboarding paths,
two state models, and remembered-Skill ambiguity. The requested product
direction is one CodeCairn-backed coding profile, so dual defaults add breadth
without increasing evidence.

### Put the Adapter in Pico

This makes Pico understand CodeCairn private storage and retrieval details and
forces every CodeCairn schema change into Pico. The Adapter belongs with the
Implementation whose details it hides.

### Use CodeCairn only through MCP

MCP is useful for explicit model-selected Tools. Memory recall and after-Turn
persistence are Runtime lifecycle operations. Making the model decide whether
to call Memory changes semantics and weakens the existing Context Seam.

### Import mutable Pico Session JSONL directly

Pico Session history can be rewritten by undo and history operations. Treating
that file as CodeCairn's append-only source would require generation and
rewrite reconciliation. A CodeCairn-owned append-only Source Journal keeps
durable import local to the Memory Adapter.

## Delivery decomposition

### CodeCairn prerequisites

The CodeCairn repository lands:

1. `v02-001`: Pico Source Journal schema, Trace importer, durable cursors, and
   evidence-preserving fixtures;
2. `v02-002`: installed `pico.plugins` Memory Adapter, repository binding,
   lifecycle, and recall/store mapping;
3. `v02-003`: mirrored joint-evidence state synchronized from Pico's final
   joint handoff.

### Pico slices

| Slice | Purpose | Depends on |
| --- | --- | --- |
| [`codecairn-001`](../tasks/codecairn-001.md) | Consume the installed Adapter, change config/onboarding, and verify fail-closed startup | CodeCairn `v02-001` and `v02-002` |
| [`codecairn-002`](../tasks/codecairn-002.md) | Remove active EverOS coupling while preserving Local Skills and historical evidence | `codecairn-001` |
| [`codecairn-003`](../tasks/codecairn-003.md) | Close continuity, distribution, and paired task evidence | `codecairn-002` and CodeCairn `v02-002`; its final handoff synchronizes CodeCairn `v02-003` |

## Integration enumeration

Each relationship needs an integration test at the creator/caller side.

| Creator/caller | Dependency | Required proof | Owner |
| --- | --- | --- | --- |
| Pico Plugin discovery | installed CodeCairn manifest | contribution resolves from a wheel with no source checkout | Pico |
| Pico base distribution | compatible CodeCairn build | fresh install cannot have an optional-missing default | Pico |
| Pico backend factory | CodeCairn Adapter | Workspace and plugin config reach the correct repository binding | both |
| Runtime Assembly | `MemoryBackend.start/stop` | one startup, one teardown, and visible failure | Pico |
| Context Memory segment | Adapter recall | user-track query returns one compiled attributed context | both |
| SkillForge | Agent-track recall | CodeCairn returns no remembered Skills; Local Skills remain | Pico |
| AgentLoop after-Turn pipeline | Adapter store | Session save precedes durable journal append and failure propagates | both |
| CodeCairn Adapter | CodeCairnApplication | blocking work runs outside the event loop | CodeCairn |
| V-O0 | installed Adapter | fresh-process recall and repository isolation | Pico |
| V-P0 | Pico and CodeCairn wheels | entry point and dependencies work outside both checkouts | both |
| PicoBench | CodeCairn live path | single-axis `null` versus `codecairn` Pair and raw evidence | Pico |

Unit tests for either side alone do not close these relationships.

## Deletion map

Deletion is a completion criterion, not cleanup for a later milestone. The
Pico replacement slice inventories and removes:

```text
pico/plugin/memory/everos/
pico/config/update_everos.py
EverOS dependency and package metadata
EverOS onboarding steps and templates
EverOS-specific Skill source and config
current EverOS-only continuity selections
current user documentation that selects EverOS
```

Before deleting a path, the implementation issue must enumerate its callers
and tests. Historical evidence documents, donor baselines, changelog history,
and operator state are not deleted or rewritten.

`understand_media` is not part of the CodeCairn Memory contract. The fastest
v0.2 path removes it with the bundled EverOS Plugin. Restoring a multimodal
Tool later requires a separate product reason and Plugin.

## State and migration

CodeCairn owns its default runtime root and repository binding. Pico does not
copy CodeCairn data under `~/.pico`.

Existing EverOS data remains untouched. The replacement provides no automatic
conversion because EverOS episodes/profiles/Skills and CodeCairn
source-attributed repository Memory do not share a lossless schema. Any future
migration must be an explicit import command with its own verifier.

## Verification strategy

### Deterministic

- manifest discovery and contribution conflicts;
- Interface contract and Adapter lifecycle;
- initialization failures and Memory-off zero calls;
- Source Journal tail recovery and prefix replay;
- same-repository fresh-process recall;
- cross-repository isolation;
- Local Skill behavior with Memory on and off;
- no EverOS dependency or bundled Plugin in the wheel.

### Real local integration

- real CodeCairn storage and index in temporary roots;
- installed Pico and CodeCairn wheels;
- CLI, TUI, and Gateway host construction against the same Adapter;
- import, process restart, and recall without either source checkout.

### Paid paired campaign

Start with:

```text
8-12 cross-session tasks
x memory off/on
x 2 repetitions
= 32-48 Trials
```

Use one Provider/model and a preregistered cost ceiling. Preserve all
Provider, infrastructure, timeout, task, and verifier outcomes. A negative
effect still completes the measurement workflow; it does not earn a positive
resume metric.

## Implemented rollout and joint result

1. CodeCairn landed its importer, Adapter, immutable distribution identity, and
   installed Pico contract smoke before Pico code changed.
2. `codecairn-001` installed the exact CodeCairn pin, switched Pico's default,
   and proved the installed Adapter lifecycle.
3. `codecairn-002` removed active EverOS coupling while preserving Session,
   Context, Local Skills, Plugin extensibility, and historical evidence.
4. V-P0 and the external CodeCairn Runtime smoke verify the Pico distribution.
5. Issue #70 completed the separately authorized installed continuity Gate and
   paid `codecairn-003` campaign. The measurement is valid, but the positive
   claim is ineligible because every hard-negative query returned three
   memories.

Before a Pico release, rollback is a Git revert plus config restoration to
`memory.backend = null`. Rollback does not reactivate a hidden EverOS
fallback. Operator EverOS and CodeCairn data remain recoverable on disk.

## Completion boundary

The Pico-side replacement is implementation-complete after
`codecairn-001` and `codecairn-002` pass their task-card Gates. Cross-repository
integration completion still requires M0 through M4 in the backend contract to
pass on one compatible Pico/CodeCairn pair under separate `codecairn-003`
authority. The evaluation Ship completes only when a separately authorized M5
records all planned terminal Trials and rebuilds its report.

Neither implementation completion nor a negative M5 result proves task uplift.
Only an eligible paired metric can support that claim.
