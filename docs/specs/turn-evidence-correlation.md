# Turn evidence correlation

How one Turn becomes one joinable evidence record: the identity that ties
Spine, Agent Loop, model, tool, memory, delivery, and usage together; the
terminal states that must stay distinguishable; and the verifier that proves
the join instead of asserting it.

Related: [`TRACING_STANDARD_API.md`](../TRACING_STANDARD_API.md) is the
write-side span standard this document consumes. This document is not the
release evidence ledger and does not grade a release; it defines one gate
(`V-TE0`) over one deterministic scenario.

---

## 1. Turn identity model

A Turn owns exactly one trace.

| id | produced by | meaning |
|---|---|---|
| `traceId` | `pico/tracing/context.py:new_trace_id` | the Turn. Every span, usage row, and delivery record for that Turn carries it. |
| `spine.turn` span id | `Lane._run_turn` | the Turn's root span. The Turn's terminal state lives here. |
| `session.turn` span id | `AgentLoop._process_message` | the Agent Loop's execution of that Turn; a child of `spine.turn`. |

The root moved from the Agent Loop to the Spine boundary because the Spine
worker, not the Agent Loop, owns the Turn lifecycle: `TurnStarted`,
`TurnFailed`, and `TurnEnded` are emitted by `Lane._run_turn`. With the root
inside `_process_message`, a cancelled or provider-failed Turn produced a
lifecycle event that no span had recorded, and a Turn cancelled before the
Agent Loop was entered produced no span at all.

Trace identity propagates by `contextvars`, so it survives `await` and the
`asyncio.create_task` snapshot. It does **not** propagate to a resident worker
task that outlives the Turn that first created it (the `DeliveryHub` outlet
worker). Those hand-offs carry the ids explicitly; see §5.

That same snapshot cuts the other way at the Spine boundary. `Lane.submit`
starts the lane worker synchronously on the submitter's context, and a Turn can
be submitted from inside an active span — `SubagentManager._announce_result`
re-injects a subagent result while `subagent.run` is open. Inheriting there
would give the new Turn the caller's trace id and parent it onto the caller's
span, putting two Turns on one trace. `Lane._run_turn` therefore opens
`spine.turn` with `trace.span(..., root=True)`, which refuses inherited context
and mints a fresh trace, so "a Turn owns exactly one trace" holds whoever
submitted it.

## 2. Span topology

```
spine.turn                     kind=session   Lane._run_turn
  session.turn                 kind=session   AgentLoop._process_message
    llm.call                   kind=model     provider.chat_with_retry / stream
    tool.call                  kind=tool      ToolRegistry.execute
    skill.read / skill.inject  kind=skill
    memory.*                   kind=memory
    subagent.run               kind=subagent
    plugin.load                kind=plugin

channel.deliver                kind=channel   DeliveryHub outlet worker
```

`channel.deliver` is drawn detached because it is emitted from the outlet
worker task, not from the Turn's task. It joins by `traceId` and parents onto
the `spine.turn` span id captured at enqueue (§5), so a viewer still renders it
inside the Turn.

`spine.turn` attributes:

| attribute | value |
|---|---|
| `spine.conversation_id` | the Lane key |
| `spine.origin` | `user` / `cron` / `subagent` |
| `spine.channel` | routing tag of the request source |
| `spine.busy_policy` | requested `TurnRequest.busy` (`append` / `inject` / `interrupt`); a non-USER origin may have it demoted by `Scheduler._effective_busy` |
| `spine.outcome` | terminal state, §3 |
| `spine.terminal_event` | `TurnStarted` (never reached a terminal), `TurnEnded`, or `TurnFailed` |
| `spine.error_class` | exception class name when the Turn raised |
| `spine.provider_error_category` | `ProviderTurnError.category` when known |
| `spine.tool_calls` / `spine.tool_failures` | counts from `TurnOutcome` |
| `spine.latency_ms` | measured for a completed Turn |

## 3. Terminal-state taxonomy

Five Turn terminal states, pairwise distinct on `spine.outcome`. The verifier
asserts distinctness rather than trusting the enum.

| `spine.outcome` | reached when | lifecycle event | span status |
|---|---|---|---|
| `completed` | runner returned an outcome, no failed Tool call | `TurnEnded` | `OK` |
| `completed_with_tool_failure` | runner returned an outcome, `tool_failures > 0` | `TurnEnded` | `OK` |
| `provider_failed` | `ProviderTurnError` escaped the runner | `TurnFailed(cancelled=False)` | `ERROR` |
| `error` | any other exception escaped the runner | `TurnFailed(cancelled=False)` | `ERROR` |
| `cancelled` | `asyncio.CancelledError` reached the worker | `TurnFailed(cancelled=True)` | `ERROR`, message `cancelled` |

`completed_with_tool_failure` is a completion, not a failure: the Turn produced
a reply and `TurnEnded`. It is separated because a Turn that answered around a
broken Tool is not the same evidence as a clean Turn, and collapsing the two
hides Tool regressions behind a green Turn count.

`cancelled` required a tracing fix. `trace.span` caught `Exception`, and
`asyncio.CancelledError` derives from `BaseException`, so a cancelled Turn
closed its span with status `OK`. The facade now catches `BaseException`,
records `ERROR` (message `cancelled` for `CancelledError`), and re-raises
unchanged. The "never breaks the caller" guarantee is unaffected: the facade
still swallows only its own failures and always re-raises the application's.

Two terminal states live outside the Turn trace and are documented here so they
are not mistaken for Turn outcomes:

- **Channel failure** — a delivery terminal, recorded on `channel.deliver`
  (`channel.outcome` ∈ `delivered` / `dropped` / `no_outlet`), §5. A Turn can
  be `completed` and its reply `dropped`; that pair is the evidence.
- **Candidate rejection** — an Evolver terminal
  (`EvidenceOutcome` ∈ `accepted` / `rejected` / `failed` / `inconclusive`),
  §7. Distinct by construction: it belongs to a different identity space.

## 4. Usage join

CallEfficiency `CallRecord` and historical `UsageSnapshot` rows carry two
optional fields, defaulting to `None`:

| field | source |
|---|---|
| `trace_id` | captured from `trace.current().trace_id` before the Provider attempt |
| `turn_span_id` | captured before the Provider attempt from the enclosing Turn span |

CallEfficiency writes `call-efficiency-YYYY-MM-DD.jsonl`; historical
`UsageTracker` writes `usage-YYYY-MM-DD.jsonl`. V-TE0 reads both schemas. Rows
written before lineage existed, or written with tracing disabled, carry `null`
and are reported as unjoinable rather than silently dropped.

**Granularity boundary.** The join is per Turn, not per model call. The Turn
identity is captured before entering retry/fallback dispatch so attempt-level
observers cannot accidentally record the active `llm.call` span as the Turn.
The `llm.call` span is the logical retry/fallback dispatch envelope and reports
the final response. The Call Record JSONL is finer-grained: each failed retry
and fallback attempt is a separate row, all joined to the enclosing Turn. There
is intentionally no one-to-one mapping between an `llm.call` span and a Call
Record.

Persistence failure is logged, written to a machine-readable ledger-health
artifact, and surfaced again at Runtime shutdown without failing the completed
Turn. V-TE0 fails on a known degraded ledger and validates the rows present; it
does not independently observe the Provider transport and therefore cannot
prove cardinality completeness when no degradation was detected. Clean shutdown
writes a terminal healthy artifact; a missing artifact makes the check
inconclusive rather than passing open. Multiple Runtime ledgers aggregate
monotonically, and V-TE0 validates both terminal counts and their per-ledger
sum before accepting a healthy state.

`TurnOutcome.usage` on `TurnEnded` is unchanged: it remains the last model
call's counts, the shape the TUI wire pins. Nothing in this document alters it.

## 5. Delivery evidence

`DeliveryHub` emits a `channel.deliver` span (kind `channel`) for the terminal
deliverables — `Text` and `MediaOut`. `StreamDelta`, `Reasoning`, `Notice`, and
`ToolEvent` do not get one: they are progress surface, and one span per stream
delta would bury the Turn.

| attribute | value |
|---|---|
| `channel.name` | outlet name |
| `channel.event` | `Text` / `MediaOut` |
| `channel.conversation_id` | Lane key when the deliverable carries one |
| `channel.attempts` | total `deliver` calls, including the first |
| `channel.retries` | `attempts - 1` |
| `channel.outcome` | `delivered` / `dropped` / `no_outlet` |
| `channel.error` | last transport error class on the `dropped` path |

**Correlation across the worker boundary.** The outlet worker is resident: one
task serves every Turn on that channel, so its `contextvars` snapshot belongs
to whichever Turn happened to create it. The hub therefore captures
`trace.current()` synchronously at enqueue — inside the Turn's task — and the
worker re-enters that trace with `trace.attach(trace_id, parent_span_id)`
before opening the span. Without this the delivery span would either mint an
unrelated trace or, worse, attach to a stale one.

**Failure propagation.** When retries exhaust, the hub builds
`Notice(kind=NoticeKind.DELIVERY_FAILED)` and hands it to an optional
out-of-band sink supplied at construction (`on_delivery_failure`). The hub
never routes that notice through `dispatch`: the channel that just failed is
the one that would have to carry the report, so re-dispatching would either
loop through the broken outlet or drop silently. Keeping the sink outside the
hub makes the non-looping property structural rather than a convention.

**Worker survival.** Every branch of the outlet worker's dispatch is wrapped so
a rendering exception is logged and the worker keeps consuming. Previously only
`_deliver_with_retry` handled its own errors, so a raising `send_stream_chunk`
killed the worker until the next enqueue restarted it, leaving its queue
unconsumed in between.

## 6. Removed conventions

New traces must not resurrect conventions the runtime removed. A deterministic
test parses every `trace.span(...)` / `trace.instrument(...)` name literal in
`pico/**` plus the viewer descriptor `type` values, and fails on any name
matching a removed subsystem: sentinel, heartbeat, nudge, skill hub, deep
research, or a removed channel. It matches span names only, not arbitrary
source text, so an unrelated identifier cannot trip it and a real emission
cannot hide behind one.

## 7. Evolver join boundary

Evolver verdicts (`pico/evolver/orchestrator/scoring.py`,
`pico/evolver/activation/artifacts.py`) key on `candidate_id` plus the run's
`work_dir` and shas. They have no session, conversation, or trace id, because a
candidate evaluation is not a Turn: it spans many trials across many processes,
and several of those trials have no conversation at all.

This document therefore records the join key rather than manufacturing one: a
candidate's evidence joins on `(candidate_id, work_dir)`, and any Turn-level
trace produced *inside* a trial joins on its own `traceId`. `V-TE0` does not
read Evolver artifacts and does not assert a cross-space join. Pushing a trace
id into the Evolver would make the two spaces look joined while the underlying
records still are not.

## 8. Verifier: `pico.turn.evidence.v1`, gate `V-TE0`

`scripts/verify_turn_evidence.py` runs a deterministic scenario in a temporary
tracing root, then validates the artifacts it produced. Every validation step
is an importable pure function taking parsed records and returning findings, so
each detector is unit-tested against corrupted fixtures rather than only
against a healthy run.

Scenario (`tests/test_turn_evidence_scenario.py`, driven through the real
`Lane` / `DeliveryHub`, one Lane per conversation):

| conversation id | drives |
|---|---|
| `scenario:completed` | success Turn with a model call, a Tool call, and a delivered reply |
| `scenario:tool_failure` | Turn completing with `tool_failures > 0` |
| `scenario:provider_failure` | runner raising `ProviderTurnError` |
| `scenario:runner_error` | runner raising a non-Provider exception |
| `scenario:cancelled` | Turn cancelled mid-run |
| `scenario:delivery_exhausted` | completed Turn whose outlet always raises |

`Scheduler` is deliberately outside the scenario. It derives the Lane key and
resolves the busy policy before a Lane runs, and neither reaches the Turn's
evidence: the scenario passes an explicit conversation id, and
`spine.busy_policy` records the requested `TurnRequest.busy`, not the policy
`Scheduler._effective_busy` applied. Lane routing, policy demotion, the
draining guard, and lane reaping are covered by
`tests/test_spine_scheduler.py`. The gate proves the Lane / DeliveryHub
evidence contract and does not claim the routing layer above it.

Validations:

1. **Turn correlation** — each scenario Turn has exactly one `spine.turn`; its
   `session.turn`, `llm.call`, and `tool.call` spans share the `traceId` and
   chain `spine.turn -> session.turn -> leaf` by `parentSpanId`.
2. **Usage join** — every usage row carrying a `trace_id` resolves to a known
   Turn, and its `turn_span_id` resolves to a span in that trace.
3. **Delivery join** — every `channel.deliver` span resolves to a known Turn,
   and an exhausted delivery has both a `dropped` span and a
   `DELIVERY_FAILED` notice.
4. **Terminal states** — the observed `spine.outcome` values are pairwise
   distinct across the scenario Turns and cover the taxonomy in §3.
5. **Contradiction detection** — an incomplete or contradictory event set is a
   finding, not a pass: a `spine.turn` with no terminal event, an outcome that
   disagrees with its span status, a `TurnEnded` outcome on an `ERROR` span, a
   `session.turn` orphaned from its root, or a usage row pointing at a trace
   that has no `spine.turn`.

Report: `.pico/evidence/turns/turn-evidence-report.json`.

| field | meaning |
|---|---|
| `schema` | `pico.turn.evidence.v1` |
| `gate` | `V-TE0` |
| `status` | shared vocabulary, below |
| `rerun` | `make verify-turn-evidence` |
| `checks.<name>.status` | shared vocabulary per check |
| `checks.<name>.evidence_class` | §9 |
| `checks.scenario.log_sha256` | sha256 of the captured scenario log |
| `turns[]` | per-Turn join summary: conversation id, trace id, outcome, span counts, usage rows, delivery outcomes |
| `findings[]` | every contradiction detected, with its detector name |

Shared status vocabulary, identical to `verify_continuity.py` and the channel
gates: `passed`, `failed`, `skipped`, `inconclusive`, `provider_failure`,
`infrastructure_failure`.

## 9. Evidence classes

A verifier must not let one kind of result stand in for another.

| class | means | used by |
|---|---|---|
| `deterministic` | a scripted, offline run with no external dependency | the scenario subprocess |
| `contract` | a schema and join assertion over records the scenario produced | correlation, usage, delivery, terminal-state checks |
| `live` | a real Provider or platform call | never produced by `V-TE0` |
| `infrastructure_failure` | the scenario could not run (timeout, missing artifact directory) | scenario check |
| `inconclusive` | the run completed but produced too little to judge (no Turns observed) | any check |

`V-TE0` passes only when the scenario is `passed` and every contract check is
`passed`. A `skipped` or `inconclusive` contract check never passes the gate.
`V-TE0` produces no live evidence and must never be reported as one.

## 10. Redaction and size rules

- The report stores conversation ids, trace ids, span ids, span names, outcome
  labels, and counts. It stores no message content, no Tool arguments or
  results, no prompt or completion text, and no Provider key or endpoint.
- Exception detail is reduced to a class name (`spine.error_class`) plus, for
  `ProviderTurnError`, its category. Exception messages are not serialized into
  the report.
- The scenario log is captured to a file next to the report and referenced by
  `log_sha256`; the report never inlines it.
- The report is a single JSON file under `.pico/evidence/turns/`. Nothing under
  that path is committed. No report assets, images, or web artifacts are
  produced by this gate.

## 11. Maintenance rules

- A new terminal state means a new `spine.outcome` value plus a scenario Turn
  that reaches it plus a row in §3. A state with no scenario Turn is not
  covered and must not be claimed as covered.
- A new `channel.outcome` value follows the same rule against §5.
- Adding a span kind is an additive change to the standard: extend
  `_KIND_BY_DOMAIN`, the frozen vocabulary test in `tests/test_tracing_api.py`,
  and the version note in `TRACING_STANDARD_API.md`.
- Changing the report shape means bumping `pico.turn.evidence.v1`. Consumers
  key on `schema`; adding a field is additive, renaming or removing one is not.
- The removed-convention list in §6 grows when a subsystem is removed. It is
  never shortened to make a test pass.
