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
