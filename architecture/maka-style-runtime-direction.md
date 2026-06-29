# Maka-Style Runtime Direction

## Decision

Pico remains a Python local code-agent harness. The next major runtime direction is
to rebuild Pico around the same product class and architecture shape that Maka has
converged toward:

- local code-agent runtime as the product center
- CLI, desktop, and headless eval as entrypoint adapters
- a shared runtime kernel under every entrypoint
- canonical runtime events as the source of truth
- headless evaluation, runtime-policy A/B, and prompt optimization as first-class
  lab capabilities

This is a runtime replacement direction, not a small v3 patch series.

## Target Shape

```text
CLI request
Desktop request
Headless eval request
        |
        v
RuntimeKernel / RuntimeRunner
        |
        v
RuntimeEvent ledger
        |
        +--> session projection
        +--> UI projection
        +--> task-run export
        +--> report / telemetry
```

The product story should be:

> Pico is a Python local code-agent runtime with built-in headless evaluation.

It should not be narrowed into a benchmark-only tool, and it should not remain a
chat-style CLI whose runtime semantics live inside the CLI loop.

## Architecture Boundaries

### CLI

The `pico` CLI stays as the user-facing entrypoint. It should become a thin
adapter that parses args, loads config, creates a runtime request, and calls the
shared runtime kernel.

It must not own the model/tool loop, prompt-history policy, completion gating,
verification semantics, run recovery, or task-ledger projection.

### Runtime Kernel

The runtime kernel owns invocation semantics:

- `RuntimeRunner`
- `InvocationContext`
- `AgentFlow`
- `ToolRuntime`
- `RuntimeEventLedger`
- `ProjectionManager`
- `RuntimeRecovery`

`RuntimeEvent` is the canonical fact model. Session messages, UI events, traces,
reports, and telemetry are projections from runtime facts.

### Headless Lab

Headless evaluation is a first-class consumer of the same runtime kernel:

- fixed-prompt controller
- task-run WAL / resume / reconciliation
- config x task runner
- protected verifier boundary
- failure taxonomy
- runtime-policy A/B
- prompt candidate loop

This layer should not leak benchmark-only verifier semantics into normal
interactive runs.

### Desktop

A desktop product is allowed and desirable if it follows the same boundary:
desktop is a projection shell and request source, not a separate runtime.

The desktop should expose sessions, tool timelines, run inspection, artifacts,
permission state, eval dashboards, and policy reports by reading projections from
the shared runtime ledger.

## Implementation Implication

Start from a clean `main`-based line rather than continuing to patch `v3`.
Existing v3 assets may be mined for tests, benchmark fixtures, and useful
features, but the old runtime loop should not remain the architectural center.

The migration order should be:

1. Add the canonical runtime event model and ledger.
2. Introduce `RuntimeRunner` and make the CLI delegate to it.
3. Move tool execution behind `ToolRuntime`.
4. Add projection/read-model layers for session, report, and trace artifacts.
5. Add headless task-run evaluation on the shared kernel.
6. Add runtime-policy A/B and prompt candidate optimization after the runtime
   baseline is stable.

The immediate success condition is not "better prompt performance." The first
success condition is that one Pico run has a single inspectable runtime truth
that can drive CLI output, reports, recovery, and eval artifacts.
