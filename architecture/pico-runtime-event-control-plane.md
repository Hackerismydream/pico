# Pico Runtime Event Control Plane

Pico keeps `Pico.ask()` as the only execution loop, but the loop is no longer
the only place where runtime policy lives. The control plane is split into a
small run context, an in-process event bus, deterministic state consumers, a
next-action planner, and a verifier driver. This is not a project-template
engine. It is a generic way to turn observed engineering artifacts into progress
pressure and verification evidence.

## Problem

The earlier completion loop could tell that a run ended poorly, but much of that
judgment happened late. A real coding task needs continuous, generic runtime
state:

- what tasks are open;
- which files became meaningful artifacts;
- what verification commands are now reasonable;
- what runtime reminders were already emitted;
- what final status should be reported if the model stops early.

Hardcoding rules like "FastAPI projects must smoke-test `/api/students`" makes
one demo pass but weakens the agent. A code agent needs evidence extraction and
soft steering that works across projects.

## Design

`Pico.ask()` creates a `RunContext` for each turn. The persisted `TaskState`
answers "what happened"; `RunContext` answers "what is left in this running
loop" such as attempts, tool steps, output-token recovery, and whether the user
message was already recorded.

`emit_trace()` writes the trace, emits the UI event, then publishes a typed
`RuntimeEvent` through `EventBus`. Each subscriber is isolated: one consumer
failure is recorded as a consumer error and does not break the agent loop.
The same payload goes to deterministic consumers:

- `TaskLedgerConsumer` snapshots the current task ledger.
- `ArtifactGraphConsumer` classifies changed paths, extracts route/API
  references from touched files, and marks artifacts as `changed`, `verified`,
  or `stale` based on recorded verification evidence.
- `VerifierSuggestionConsumer` suggests commands from project metadata such as
  `package.json`, Python test files, and changed Python source.
- `VerifierDriverConsumer` builds a `verification_plan`: requirements, suggested
  commands, static checks, and missing evidence.
- `ReminderConsumer` records runtime reminders in structured state.

The main loop still owns model calls, tool execution, approvals, provider
recovery, session save, and checkpointing. The new `RuntimeControlPlane` owns
only three control decisions:

- `before_tool`: emit or enforce progress reminders before a tool call.
- `after_tool`: keep a single extension point for tool-result policy.
- `before_final`: decide whether a proposed final answer has enough evidence.

Consumers do not call tools and do not talk to the model. The control plane can
select a verifier action when a final answer is blocked by missing verification,
but the action still goes through the normal `run_shell` tool path, policy,
trace, session event, and `VerificationArtifact` recording. There is no hidden
side channel.

`RuntimeControlPlane` owns the small next-action planner internally. This is
where task pressure, artifact pressure, verification pressure, and budget
pressure converge. Its output is explicit: allow, remind, reject, block final,
or propose a concrete next tool.

## Soft Guidance vs Hard Stops

Hard stops remain for protocol and safety: invalid tool args, prior-read policy,
path policy, approval denial, repeated identical tool calls, provider failure,
and step limits.

Completion is now a real gate for project-changing work:

- open tasks block final answers;
- changed files that require verification block final answers until a passed
  `VerificationArtifact` exists;
- failed static checks from the verification plan block final answers;
- when a safe, short verifier command is available, a blocked final can trigger
  a normal `run_shell` verification action before the model is asked again;
- reminders are injected once per reason, then repeated stale behavior can be
  rejected;
- reports expose artifact graph, verification plan, control decisions, and
  reminders.

This keeps the runtime honest without pretending it can solve every project by
adding another domain-specific constraint. The gate should return a concrete
next action rather than a vague scolding.

## Reference Fit

The design follows the useful shape of `cc/pimono code agent`:

- Claude Code style: tool loop stays central, reminders and hooks steer behavior
  around the loop, and Todo-style state becomes visible runtime evidence.
- pi-mono code agent style: events form the extension surface, so UI/reporting
  and derived state do not get tangled into the core model loop.

Pico does not copy either implementation. The point is the same architecture
principle: keep the control plane generic, event-driven, and observable.

## Current Interfaces

New persisted `TaskState` fields:

- `artifact_graph`
- `verification_plan`
- `control_decisions`
- `runtime_reminders`
- `consumer_errors`

Reports now include the same fields. This makes one run auditable even when the
model tried to stop before the task was actually complete.

## Verification Plan

`VerifierDriver` converts artifact evidence into requirements:

- Python source or tests produce `python_syntax_or_tests`.
- Package metadata or frontend code produces `package_build_or_test`.
- Frontend API references plus backend routes produce `api_consistency`.
- Documentation changes produce `docs_startup_consistency`.

The driver can suggest commands, such as `npm test`, `npm run build`,
`uv run python -m pytest -q`, or
`uv run --with-requirements requirements.txt python -m compileall .`.
It can also run static reasoning over already-extracted artifacts, such as
checking whether a frontend API reference is covered by a backend route.

When a verification plan has missing evidence, `select_verification_action()`
can turn the first safe suggestion into a normal tool action:

```text
verification_plan -> run_shell(command, timeout=60) -> VerificationArtifact
```

The first executable scope is intentionally conservative: only built-in Python
syntax/test commands are auto-selected. Package scripts such as `npm test` and
`npm run build` remain visible suggestions, but they are not auto-executed
because project-defined scripts can contain arbitrary commands. The verifier
does not start long-running services or invent business smoke tests.

This is not a hidden verifier and not a business template. It does not know what
a student manager is. It only knows that generated engineering artifacts imply
generic engineering checks.
