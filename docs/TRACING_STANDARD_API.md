# Tracing Standard API v1

> Status: current in-tree write-side contract.
>
> This API is implemented and conformance-tested. V-TE0 correlates traces,
> usage, Channel delivery, and Turn terminal state as deterministic contract
> evidence; [Issue #23](https://github.com/Hackerismydream/pico-harness/issues/23)
> is closed. Full release aggregation remains the separate V-R0 boundary.

The contract between **Pico** and its in-tree tracing implementation,
`pico.tracing`.

Principle: *tracing owns the standard, the runtime adopts it.* The in-tree
tracing subsystem defines what a span is, which fields each span kind carries,
and how it renders. Pico instruments itself through one small, stable facade —
`trace.span(...)` — at points it chooses. Instrumentation code does not depend
on storage or viewer internals; its coupling is limited to this API version and
the semantic conventions below.

`pico.tracing` ships inside the `pico-harness` distribution. There is no
separate tracing distribution or compatibility import under the donor
namespace.

This mirrors the OpenTelemetry model (library defines the API + data model; the
app does manual instrumentation), so the same discipline applies: the API is
tiny and slow-moving, the SDK behind it (storage, viewer, on-disk format) iterates
freely without touching adopters.

Related: the on-disk record shape (`audit.span.v1`) is defined in
`pico/tracing/spans.py` (`build_span`) and summarized in §2; this document is
the **write-side** standard that produces those records.

---

## 1. Public API

One import, one primary call:

```python
from pico.tracing import trace

with trace.span("llm.call", {"llm.provider": provider, "llm.model": model}) as s:
    resp = do_call(...)
    s.set({"llm.usage.total_tokens": resp.usage.total, "llm.finish_reason": resp.finish_reason})
```

### `trace.span(name, attributes=None, *, kind=None, session_key=None, channel=None, chat_id=None, detached=False, root=False, **kw) -> Span`

A context manager that opens a span on enter and finalizes + records it on exit.

- `name` — dotted semantic name, `<domain>.<verb>` (e.g. `llm.call`). Drives the
  default `kind` and the viewer's label/rendering (see §2).
- `attributes` — a mapping of fully-qualified dotted keys (the standard form,
  e.g. `{"llm.provider": p, "llm.model": m}`). Standard keys are dotted, so a
  mapping is the primary form; `**kw` accepts bare keys for convenience (stored
  verbatim, no auto-namespacing — the attribute namespace can differ from the
  name domain, e.g. `session.turn` carries `turn.*`).
- `kind` — optional override of the coarse category
  (`session|model|tool|subagent|skill|memory|plugin`). Default derived from the
  name's domain; pass explicitly for custom nodes (§3).
- `root` — refuse any inherited context: mint a fresh trace with no parent,
  whatever the task carries. For a span that *defines* an identity rather than
  joining one; `spine.turn` passes it, because a Turn submitted from inside an
  active span (a subagent re-injecting its result) must still own one trace.

Nesting is automatic via `contextvars`: a span opened while another is active
becomes its child; context survives `await` and is snapshotted onto tasks. The
root of a turn is a `spine.turn` span opened at the Spine boundary; the agent
loop's `session.turn` and everything else nests beneath it.

### `Span` handle

| method | effect |
|---|---|
| `s.set(attrs=None, **kw)` | merge attributes onto the span (dotted-key mapping and/or bare kwargs) |
| `s.artifact(key, payload, *, kind="json")` | persist a large payload out-of-line; attach `<key>.artifact_path/_sha1/_bytes` + a truncated `preview`. Use for prompts / tool IO / recall results. |
| `s.event(name)` | append a timeline event `{time, name}` |
| `s.error(exc)` | mark `status = ERROR` (done automatically if the block raises) |

Read-only: `s.trace_id`, `s.span_id`, `s.name`.

### Module helpers

| call | returns |
|---|---|
| `trace.enabled()` | whether recording is on (config/env) |
| `trace.current()` | the active `TraceCtx` or `None`; fields include trace/session/channel identity, nearest parent span id, and current source |
| `trace.attach(trace_id, parent_span_id)` | context manager: re-enter an existing trace on a task that did not inherit it |

`trace.attach` exists for *resident* workers — one task serving many turns, so
its `contextvars` snapshot belongs to whichever turn happened to start it. Such
a worker captures the ids at hand-off and re-attaches before opening its span,
instead of minting an unrelated trace or silently reusing a stale one. A falsy
`trace_id` is a no-op.

### Hard guarantees (why an adopter is safe)

1. **No-op when off.** If disabled (config) or no SDK backend is active,
   `trace.span(...)` yields a no-op handle: no I/O, near-zero overhead, the
   `with` block runs normally.
2. **Never breaks the caller.** The facade swallows *its own* failures (bad
   attribute, disk error, SDK bug) and logs at debug level. It re-raises the
   *application's* exception unchanged (after recording `status=ERROR`). A
   tracing bug can never alter or crash the host's control flow. The handler
   catches `BaseException`, not `Exception`, so a cancelled block records
   `status=ERROR` with message `cancelled` — an `Exception`-only handler closed
   cancelled spans as `OK` — and every caught exception is still re-raised
   unchanged.
3. **Import-safe.** Importing `pico.tracing` and calling the API must succeed
   even with no config present.

### `@trace.instrument(...)` — the decorator (primary adopter mechanism)

Adopters instrument a method by annotating it — the body is untouched, so this
does not change core logic (only adds an observation wrapper)::

    @trace.instrument("llm.call", extract=semconv.llm_call)
    async def chat_with_retry(self, ...): ...

`trace.instrument(name, *, kind=None, detached=False, seed=None, on_open=None, extract=None)`
wraps a sync **or** async method:

- `extract(span, bound_args, result, exc)` — runs in `finally` (input captured
  even on error); fills final attributes/artifacts. `bound_args` is the call's
  arguments by name; `result` is the return (`None` on error); `exc` the raised
  exception (`None` on success). The standard extractors live in
  :mod:`pico.tracing.semconv` (`llm_call`, `tool_call`, `memory_*`, …).
- `seed(bound_args) -> dict` — returns `session_key` / `channel` / `chat_id` to
  open a *root* span (a turn) whose identity every child inherits.
- `on_open(span, bound_args)` — runs right after open, before the body; used to
  record input and `span.checkpoint()` an in-progress root for live viewing.

Extra `Span` methods used by extractors: `span.retype(name, kind)` (a `tool.call`
that turns out to be a `skill.read`), `span.cancel()` (drop a conditional span,
e.g. `skill.inject` only when something was injected), `span.checkpoint()`,
`span.elapsed_ms()`. Pass `detached=True` for a leaf marker that does NOT become
the active parent — required for cancellable spans so a child that opened before
the cancel doesn't dangle off an unemitted span.

Every span family is instrumented this way — including `subagent.run`: a
subagent runs the same decorated primitives (`chat_with_retry` / `tools.execute`),
so its spans are captured by those decorators and nest under the `subagent.run`
node automatically via the contextvars snapshot `asyncio.create_task` takes at
spawn. No monkeypatch is used anywhere.

---

## 2. Semantic conventions (standard span kinds)

`kind` is a single-word category (drives node coloring/grouping). `name` is the
`<domain>.<verb>` identifier (drives the label + rendering). Attributes are
namespaced by domain. Adopters SHOULD populate the "required" columns; "optional"
adds richer rendering.

| name | kind | required | optional attributes |
|---|---|---|---|
| `spine.turn` | `session` | `spine.outcome` | `spine.conversation_id`, `spine.origin`, `spine.channel`, `spine.busy_policy`, `spine.terminal_event`, `spine.error_class`, `spine.provider_error_category`, `spine.tool_calls`, `spine.tool_failures`, `spine.explicit_reply`, `spine.latency_ms` |
| `session.turn` | `session` | — | `turn.input_preview`, `turn.output_preview`, `turn.in_progress`, `turn.capabilities.{tools,plugins,skills}` |
| `llm.call` | `model` | `llm.provider`, `llm.model` | `llm.provider_class`, `llm.finish_reason`, `llm.call_id`, `llm.invocation_source`, `llm.usage.{input,output,total,cache_read,cache_write}_tokens`, `llm.usage.cost_total`; artifacts `llm.input` (messages+tools), `llm.output` |
| `tool.call` | `tool` | `tool.name` | `tool.call_id`, `tool.duration_ms`, `tool.error`; artifacts `tool.input` (params), `tool.output` (result) |
| `channel.deliver` | `channel` | `channel.name`, `channel.outcome` | `channel.event`, `channel.conversation_id`, `channel.attempts`, `channel.retries`, `channel.error` |
| `subagent.run` / `subagent.call` | `subagent` | — | `subagent.id`, `subagent.label`, `subagent.task`, `subagent.session_id`, `subagent.parent_trace_id`, `subagent.parent_span_id`, `subagent.trace_id`, `subagent.status` |
| `skill.read` / `skill.inject` | `skill` | - | `skill.name`, `skill.path`, `skill.read.via_tool` (`read_file`), `skill.inject.{names,count,via}` |
| `memory.recall` / `.store` / `.feedback` / `.extract` / `.consolidate` / `.profile_refresh` | `memory` | — | `memory.scope`, `memory.hits`, `memory.message_count`, `memory.kind`, `memory.deposit_summary`, `memory.deposit_status`, `memory.surface`, `memory.sections_rewritten`; artifacts per op |
| `plugin.load` / `tracing.bootstrap` | `plugin` | — | `plugin.name`, `plugin.contribution`, `plugin.id` |

**Provider labeling:** `llm.provider` is the *logical backend* the call routes to
(e.g. `openrouter`), derived from the model's gateway prefix; `llm.provider_class`
is the concrete class (e.g. `LiteLLMProvider`) when it differs.

**Call ids:** `llm.call_id` is the model call's trace-local identifier — the
`llm.call` span's own id, stable across the retry ladder that one logical call
may run through, so an artifact or viewer can key on it after a `retype`.
`tool.call_id` is the *model's* tool-call id, passed by the caller into
`ToolRegistry.execute`; it is omitted (not synthesized) when the caller has
none, so the attribute never mixes two id spaces.

**Turn root:** `spine.turn` is the root of a turn's trace and carries its
terminal state; `session.turn` is the agent loop's execution of that turn and
nests beneath it. `spine.outcome` is a closed vocabulary:
`completed|completed_with_tool_failure|provider_failed|error|cancelled`. See
[`specs/turn-evidence-correlation.md`](specs/turn-evidence-correlation.md).

**Delivery:** `channel.deliver` is emitted from a resident outlet worker, so it
re-enters the turn's trace with `trace.attach(trace_id, parent_span_id)` using
ids captured at enqueue. `channel.outcome` is a closed vocabulary:
`delivered|dropped|no_outlet`.

Naming rules:
- `name` = `<domain>.<verb>`, lowercase dotted.
- attribute keys = `<domain>.<field>`, matching the span's domain.
- kind is a closed vocabulary:
  `session|model|tool|subagent|skill|memory|plugin|channel`.

---

## 3. Custom nodes

Any adopter (or plugin) may record a custom span — no registration required:

```python
with trace.span("pico.plugin.refresh", {"plugin.reason": r}, kind="plugin") as s:
    s.set({"plugin.updated": n})
```

Rules:
- Use an **owned namespace** for `name` (`pico.<subsystem>.<verb>`) to avoid
  clashing with the standard names in §2.
- Pass `kind` explicitly (falls back to a generic node kind otherwise).
- The viewer renders unknown names generically (title from `name`, subtitle from
  a chosen attribute). For bespoke rendering, ship a **descriptor** entry
  (`descriptors/*.json`, keyed by `type`) — the viewer's rendering standard,
  shipped under `pico/tracing/viewer/descriptors/`.

---

## 4. Adopter integration contract (Pico)

1. Tracing ships in the base `pico-harness` wheel as the in-tree
   `pico.tracing` package. It is not an optional extra or a separately
   installed dependency.
2. Use `from pico.tracing import trace` at instrumentation sites and wrap the
   operation in `with trace.span(...)`. Instrumentation lives in Pico's own
   source, moves with refactors, and is visible in diffs (no external
   monkeypatch to silently break).
3. Enable/disable via `[tracing].enabled` (Pico config) or `PICO_TRACING=0`
   (env override). The API no-ops when disabled.
4. The app never imports the SDK internals (storage/viewer) — only the facade.

There is no monkeypatch / auto-instrumentation path: all instrumentation is the
explicit `@trace.instrument` annotations in Pico's own source, so it moves with
the code and shows up in diffs (never silently breaks on a refactor).

---

## 5. Versioning & governance

- The API + semantic conventions are versioned together as `standard-api.v1`,
  independent of the app.
- **Additive** changes (new optional attribute, new span name/kind) → minor bump,
  backward compatible.
- **Breaking** changes (rename/remove an attribute or the API signature) → major
  bump + a migration note in the Pico release that carries the change.
- A conformance snapshot test (frozen span names + required fields) guards the
  contract in CI; changing it without a version bump fails the build.
- On-disk record format is versioned separately as `audit.span.v1`
  (defined in `pico/tracing/spans.py`); the two move independently.

**Additive changes in this revision** (backward compatible, no adopter break):
the `channel` span kind, the `spine.turn` and `channel.deliver` conventions, the
`trace.attach` helper, and `llm.call_id` / `tool.call_id` emission. Existing
span names, attributes, and the `audit.span.v1` record shape are unchanged, so
a reader written against the previous revision still parses every record.

---

## Implementation status

In-tree, complete. Every span family (spine.turn / session.turn / llm / tool /
memory / skill.inject / plugin.load / subagent / channel.deliver) is
instrumented on Pico's own methods — `@trace.instrument` where a method is the
unit, an explicit `trace.span` where the unit spans a control-flow block (the
Spine worker's turn, the outlet worker's send). There is no monkeypatch and no
`instrument.install()` — the auto-probe module was removed. `semconv.py` owns
the standard attribute/artifact builders.

Turn correlation is implemented: one trace spans Spine, agent loop, model, tool,
memory, and channel delivery, usage rows carry `trace_id` / `turn_span_id`, and
the five Turn terminal states are distinguishable on `spine.turn`. The
`V-TE0` gate (`make verify-turn-evidence`) proves the join on a deterministic
scenario; its contract is
[`specs/turn-evidence-correlation.md`](specs/turn-evidence-correlation.md).

This document is the write-side span standard, **not the release evidence
ledger**: it defines what a span carries, not whether a release is fit to ship.

Tracing is part of the base `pico-harness` distribution. The product, command,
configuration, state, and Python module paths are Pico-owned. There is no
published standalone tracing package, compatibility namespace, or tracing extra
in the current packaging contract.

Tracing is best-effort local observability, not the release evidence ledger.
The facade deliberately swallows its own failures, and the local JSONL store is
not an OpenTelemetry exporter or a cross-process transactional log. See
[Project status](project-status.md) for the current evidence boundary.
