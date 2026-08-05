# CodeCairn Memory backend contract

> **Status: implemented and jointly verified for the accepted Pico Harness
> v0.2 engineering/product milestone; M2, M4, and M5 have explicit results and
> this is not a package-semver declaration.**
> Pico now consumes the installed CodeCairn Adapter and has removed active
> EverOS product coupling. Historical EverOS evidence remains valid only for
> the commits and experiments that produced it.

## Outcome

The Pico Harness v0.2 milestone uses CodeCairn as its long-term Memory
backend:

```text
Pico Hosts
  -> Spine -> AgentTurnRunner -> AgentLoop
     -> Session
     -> ContextAssembler
        -> MemoryBackend Interface
           -> CodeCairn Memory Adapter
              -> CodeCairnApplication
                 -> repository-scoped durable Memory and recall
     -> Local Skills
     -> Tool / MCP
```

The user-facing selection is:

```json
{
  "memory": {
    "backend": "codecairn"
  }
}
```

`memory.backend = null` remains the only implicit-Memory-off baseline. Pico
does not retain EverOS as a hidden fallback.

This is a replacement, not an additional orchestration layer. Pico keeps the
Runtime, Session, Context, Tool, Local Skill, and evaluation Modules.
CodeCairn owns repository Memory ingestion, storage, retrieval, and the Adapter
that implements Pico's existing `MemoryBackend` Interface.

## Product reason

Pico's current Memory Module can persist and recall information across
Sessions, but its default integration is user- and Agent-track oriented.
CodeCairn adds the repository identity, source provenance, freshness, durable
Markdown truth, and retrieval profile needed by a coding-focused Pico profile.

The v0.2 product claim is deliberately narrow:

> A Pico Turn can persist its completed trajectory into CodeCairn and a fresh
> Pico process in the same repository can recall relevant, source-attributed
> context before the next Turn.

This contract does not claim that CodeCairn improves task success. That claim
requires the paired evaluation defined below.

## Joint evidence result

Issue [#70](https://github.com/Hackerismydream/pico-harness/issues/70#issuecomment-5128723096)
completed the joint Gate against Pico commit `5318daa` and CodeCairn commit
`a501fe2`:

- M2 and M4 passed the installed, source-checkout-free continuity Gate;
- M5 completed 32/32 formal Trials and 16/16 valid Pairs;
- CodeCairn passed 16/16 task Verifiers versus 0/16 for Memory-off;
- Recall@5 was 1.0, with zero stale injections, zero cross-repository leakage,
  and zero Memory-off CodeCairn operations;
- `positive_claim_eligible=false` because every hard-negative query returned
  three rendered memories, producing an irrelevant-injection rate of 3.0
  against the frozen maximum of 0.05.

This is a valid task measurement and an explicit product defect. It is not an
eligible positive resume claim. The experiment's empty `cv-metrics.json`
enforces that boundary.

## Module ownership and dependency direction

| Module | Owner | Responsibility |
| --- | --- | --- |
| `MemoryBackend` Interface and lifecycle calls | Pico | Stable Runtime seam, start/stop ordering, recall/store/feedback invocation, and failure propagation |
| CodeCairn Memory Adapter | CodeCairn | Installed `pico.plugins` contribution implementing `MemoryBackend` |
| Pico Source Journal | CodeCairn | Durable append-only capture of Pico turn slices before import |
| Pico source importer | CodeCairn | Normalize journal records into CodeCairn Agent Trace without inventing evidence |
| Repository identity and retrieval profile | CodeCairn | Bind writes and recall to the repository selected by `codecairn init` |
| Recall compilation and packing | CodeCairn | Rank, budget, render, and attribute one Recall Context |
| Default backend selection and onboarding | Pico | Select `codecairn`, explain initialization, and fail closed on invalid setup |
| EverOS removal | Pico | Keep the bundled Plugin, direct dependency, onboarding path, active docs, and current Gates absent |
| Local Skills | Pico | Preserve Local Skill loading and routing independently of CodeCairn |
| Distribution and continuity evidence | Pico | Verify installed Plugin discovery, fresh-process recall, and host parity |
| Paired task evaluation | Pico | Compare `null` with `codecairn` under one frozen PicoBench plan |

Dependency direction:

```text
Pico source -> MemoryBackend Interface
CodeCairn distribution -> Pico plugin manifest and Adapter Implementation
Pico source -X-> CodeCairn private modules
CodeCairn core -X-> Pico Runtime composition
```

Pico's base distribution installs a compatible CodeCairn build because a fresh
Pico config selects `codecairn`. CodeCairn is not an optional missing default.
The implementation uses the immutable pre-release identity accepted by the
CodeCairn handoff and verifies that combination through V-P0:

```text
codecairn @ git+https://github.com/Hackerismydream/CodeCairn.git@e993eb562cf1bb0b89490de4e91c2a56d79eb3be
```

Local paths and floating branches are not valid defaults.

Pico discovers the Adapter through the installed `pico.plugins` entry-point
group. The CodeCairn package keeps its entry-point package import lightweight.
Pico distribution metadata may depend on CodeCairn; Pico Runtime and Context
source must not directly import CodeCairn private modules.

The three identifiers are distinct and fixed:

| Identifier | Target |
| --- | --- |
| Python entry-point name | `codecairn` |
| Plugin manifest id | `codecairn-memory` |
| Memory backend contribution | `codecairn` |

Expected CodeCairn distribution entry point:

```toml
[project.entry-points."pico.plugins"]
codecairn = "codecairn.integrations.pico"
```

Expected installed Plugin contribution:

```toml
[plugin]
id = "codecairn-memory"
version = "0.1.0"
bundled = false
enabled_by_default = true

[[plugin.contributes.memory_backends]]
name = "codecairn"
factory = "codecairn.integrations.pico.backend:make_backend"
```

Resource package
`codecairn.integrations.pico`, entry-point name `codecairn`, Plugin id
`codecairn-memory`, and backend contribution name `codecairn` are public
cross-repository identifiers. The resource package contains a cheap
`__init__.py` and the manifest; its leaf Adapter modules may evolve. Changing a
public identifier requires both repositories to update their contract tests in
the same delivery sequence.

## Operator contract

The operator performs one explicit CodeCairn initialization in the target Git
repository:

```bash
codecairn init
```

Pico startup does not silently create a CodeCairn repository binding, change a
retrieval profile, or initialize a non-Git directory. When
`memory.backend = "codecairn"` is selected, startup validates:

1. the CodeCairn distribution and Plugin manifest are installed;
2. the Workspace granted through `PluginContext.services.workspace` resolves
   to an initialized CodeCairn repository without consulting process cwd;
3. the repository identity and retrieval profile are valid;
4. configured provider and index requirements are satisfiable;
5. the selected CodeCairn runtime root is not the Pico Workspace.

Any failure aborts Memory startup with actionable remediation. There is no
empty-Memory fallback for configuration, import, index, or persistence
failure. A successful zero-hit recall is represented only by an empty result
from a healthy backend.

The initial Pico-owned configuration surface is deliberately narrow:

```json
{
  "memory": {
    "backend": "codecairn",
    "memoryTopK": 5
  }
}
```

The first release has no Pico-side CodeCairn runtime-root, repository, or
retrieval-profile override. Those values and credentials remain in the
CodeCairn configuration selected by `codecairn init`; they must not be copied
into Pico config or evidence.

## `MemoryBackend` mapping

The first Adapter release preserves Pico's current structural Interface.

### `start()`

`start()` resolves the Pico Workspace to the CodeCairn repository identity,
loads the initialized configuration, opens CodeCairn, validates the retrieval
profile, and imports any durable uncommitted Pico Source Journal suffix.

CodeCairn operations are synchronous today. The Adapter executes blocking
start, import, store, index, and recall calls through `asyncio.to_thread` so a
Pico host event loop is not blocked.

### `recall(query, user_id=..., top_k=...)`

Pico's user track maps to CodeCairn repository recall:

- Pico `user_id` is not a namespace and does not select a CodeCairn
  repository;
- the initialized repository identity selects the namespace;
- `top_k` maps to the CodeCairn recall limit;
- CodeCairn owns ranking, freshness filtering, token budgeting, and rendering;
- the Adapter must not rerank or independently repack CodeCairn results.

The Adapter returns one Pico `Memory` containing the compiled CodeCairn Recall
Context. Pico's public contract requires a concrete `Memory` instance. The
Adapter therefore imports that public carrier lazily while CodeCairn core and
its entry-point resource package remain Pico-free. Its metadata includes only
system-derived attribution:

```text
backend = codecairn
repo_key
rendered_memory_ids
source_uris
freshness
source_cursor
index_cursor
retrieval_profile
score_semantics = compiled_context_not_ranked
```

The compiled Recall Context has no single comparable ranked score, so
`Memory.score` is fixed at `0.0`. The Adapter must not invent a normalized
aggregate.

Raw recalled content and credentials do not enter generic Pico traces or
benchmark summaries.

### `recall(query, agent_id=..., top_k=...)`

The CodeCairn Adapter returns `[]` for Pico's Agent track in v0.2. CodeCairn
does not replace Pico Local Skills and does not masquerade repository Memory
as remembered Skills.

The EverOS-backed Skill source and its weighted fusion are removed from the
default v0.2 profile. Local Skills remain available with Memory enabled or
disabled.

### `store(session_id, messages)`

Pico calls `store` once after an after-Turn slice has been saved to the Pico
Session. Pico must derive the backend slice from the same normalized message
view it persisted, excluding Runtime-only context tags, recovery scaffolding,
and any field rejected by Session persistence. The Adapter:

1. validates the repository binding;
2. appends the turn slice to a CodeCairn-owned Pico Source Journal;
3. durably flushes that append;
4. imports the committed journal suffix into CodeCairn Agent Trace with
   boundary `pico_turn_end`;
5. persists derived Memory and index work according to CodeCairn's contract;
6. returns only after the write is recall-visible or fails.

The Pico Source Journal is append-only JSONL under the CodeCairn runtime root.
CodeCairn owns its physical path, schema version, cursor, crash-tail handling,
and compaction policy. Pico receives no journal path configuration.

The first record schema is logically:

```text
schema = codecairn.pico.source.v1
repo_key
source_session_id
journal_sequence
record_kind
role
content
tool_call
tool_result
source_timestamp
```

The importer may normalize a record as a message, Tool call, Tool result,
metadata, or unknown Trace event. Boundary `pico_turn_end` closes an Episode
but does not assert task success. The current `MemoryBackend.store` input does
not carry a typed `TurnOutcome`, so terminal outcome remains `unknown` unless
Pico supplies a recognized structured fact. Arbitrary assistant or Tool-result
text is untrusted and cannot become verified evidence.

Current Pico invokes backend `store` once per persisted AgentLoop after-Turn
slice that reaches the pipeline. A stored slice may include Tool failures and
must not be relabeled as a successful task. The v0.2 idempotency guarantee
covers:

- replay of an already committed Pico Source Journal prefix;
- restart after append and before import completion;
- restart after import and before cursor persistence.

It does not claim that two independent, identical `store` calls from an
arbitrary caller are the same Turn. If Runtime delivery later needs that
guarantee, Pico must add a stable persisted Memory batch identity to the
Interface rather than ask the Adapter to deduplicate by message text.

### `feedback(signals)`

`feedback` is an Interface-compatibility no-op in v0.2. Local Skill feedback
stays Pico-owned. The Adapter accepts direct contract-test calls without
creating a synthetic CodeCairn confidence update; it is not a required live
integration campaign step.

### `stop()`

`stop()` drains Adapter-owned import/index work, persists cursors, closes
CodeCairn resources, and remains safe after a partially failed `start()`.
Pico must let Runtime Assembly finish other teardown, then expose a backend
stop failure as a host shutdown failure rather than only logging it as a clean
shutdown.

## Failure and consistency semantics

The cross-store order is:

```text
Pico Session save
  -> CodeCairn Source Journal append
  -> CodeCairn import and durable Memory commit
  -> later or fresh-process CodeCairn recall
```

Pico Session and CodeCairn are not one transaction. The accepted recovery
semantics are:

| Failure point | Durable state | Required behavior |
| --- | --- | --- |
| Before journal append | Pico Session only | Turn fails after Session save; retry can submit a new Turn |
| During journal append | Pico Session plus valid prefix | Ignore or truncate invalid tail; do not import it |
| After append, before import | Pico Session plus complete journal record | `start()` or next store resumes import |
| After import, before cursor update | Imported data plus older cursor | Replay is idempotent; no duplicate durable Memory |
| During recall | Existing durable state | Recall fails visibly; do not return stale cached content as success |

This contract does not provide mid-Turn recovery, external-side-effect
exactly-once semantics, or a transaction spanning Session, CodeCairn, Trace,
and Delivery.

## Transition from EverOS

The completed Pico-side replacement removed:

- bundled `everos-memory` Plugin and `understand_media` contribution;
- direct EverOS dependency and package data;
- EverOS onboarding and config mutation;
- EverOS remembered Skill source and active routing configuration;
- current docs, tests, and Gates that require EverOS as the selected backend.

The delivery preserves:

- Local Skills and their BM25 path;
- historical EverOS evidence and experiment reports;
- operator EverOS data on disk;
- `memory.backend = null`;
- third-party `MemoryBackend` Plugin discovery.

Pico does not auto-migrate, delete, or rewrite `~/.everos/pico`. Operators may
re-import supported source material through CodeCairn tooling, but v0.2 does
not promise an EverOS state conversion.

## Cross-repository delivery sequence

```text
CodeCairn v02-001: Pico Source Journal and importer
  -> CodeCairn v02-002: installed Pico Memory Adapter
     -> Pico codecairn-001: consume Adapter and switch default
        -> Pico codecairn-002: remove EverOS coupling, preserve Local Skills
           -> Pico codecairn-003: joint evidence campaign
              -> CodeCairn v02-003: mirrored evidence state-sync
```

Pico does not merge the default switch before an installed CodeCairn wheel can
pass the Adapter contract in a clean environment.

## Acceptance Gates

### M0: Interface and package identity

- Pico's base distribution installs a resolvable compatible CodeCairn build;
- CodeCairn publishes entry point `codecairn` and one discoverable
  `codecairn-memory` Plugin manifest;
- Pico resolves backend contribution `codecairn` without a source-tree import;
- `pico/` does not import CodeCairn private modules;
- the installed Plugin passes Pico's public `MemoryBackend` contract tests.

### M1: initialization and failure behavior

- an initialized Git repository starts successfully;
- missing initialization, invalid profile, missing provider, and unavailable
  index each fail closed with remediation;
- `memory.backend = null` performs zero CodeCairn factory, lifecycle, recall,
  store, feedback, journal, import, and index calls; entry-point discovery and
  cheap module import may still occur;
- CodeCairn operations do not block the host event loop.

### M2: durable write and recall

- a normalized Pico after-Turn slice is durably appended before import;
- the first batch closes one `pico_turn_end` Episode without asserting task
  success;
- crash-tail and journal-prefix replay are deterministic;
- a fresh Pico process in the same repository recalls the stored context;
- repository A content is never recalled in repository B;
- the Adapter returns one attributed Recall Context and does no extra ranking.

### M3: product replacement

- fresh Pico config selects `codecairn`;
- Local Skills work with CodeCairn on and off;
- the Pico wheel has no bundled EverOS Plugin or direct EverOS dependency;
- onboarding, diagnostics, and installed CLI/TUI/Gateway hosts use the same
  CodeCairn selection;
- no current document presents historical EverOS evidence as CodeCairn proof.

### M4: continuity and distribution

- the separately authorized CodeCairn continuity Gate covers store, process
  restart, recall, repository isolation, and Memory-off zero backend-operation
  calls;
- V-P0 installs Pico and CodeCairn wheels without a source checkout;
- host parity runs against the installed Adapter;
- reports bind Pico commit, CodeCairn commit/version, wheels, config, and
  repository fixture digest.

### M5: paired evaluation

PicoBench creates a new experiment identity and compares:

```text
control:   memory.backend = null
treatment: memory.backend = codecairn
```

The Pair keeps model, prompt, Tool set, Local Skills, token budget, Workspace,
timeout, retry policy, and verifier fixed. The treatment must exercise the
live path:

```text
Pico store
  -> CodeCairn journal/import/index
  -> fresh process recall
  -> task-level deterministic Verifier
```

The first campaign targets 8-12 cross-session tasks, two arms, and two
repetitions. It reports verifier pass rate and paired delta, expected recall
ids, input and total tokens, latency, Tool calls, repeated repository reads,
Memory failures, and cross-repository leakage.

Negative or inconclusive results may complete the integration Ship, but only a
preregistered eligible metric may become a resume claim. New CodeCairn
artifacts must not overwrite or relabel PicoBench's historical EverOS
experiments.

## Non-goals

- making CodeCairn own Pico Runtime, Session, Context, Tools, or Local Skills;
- mounting CodeCairn through MCP instead of the Memory Interface;
- retaining EverOS as a fallback or dual-write target;
- treating CodeCairn repository identity as Pico `user_id`;
- importing unverified model claims as command or task-success evidence;
- automatic migration or deletion of EverOS state;
- cross-repository recall;
- mid-Turn recovery or external-side-effect exactly-once behavior;
- a positive task-uplift claim unless M5 Positive Claim Eligibility passes.
