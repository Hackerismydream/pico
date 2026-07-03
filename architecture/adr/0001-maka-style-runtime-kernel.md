# ADR 0001: Rebuild Pico Around a Maka-Style Runtime Kernel

## Status

Accepted

## Context

Pico's product direction is a Python local code-agent runtime with built-in
headless evaluation. The current v3 runtime accumulated CLI, session, context,
memory, tool, trace, report, and benchmark concerns around a hand-written loop.
That shape makes the runtime hard to reason about, hard to recover, and hard to
evaluate.

Maka has converged on the same product class with clearer boundaries:

- entrypoints are adapters
- runtime invocation is owned by a kernel and runner
- runtime events are canonical facts
- session, UI, trace, report, telemetry, and task exports are projections
- headless evaluation and prompt/runtime-policy optimization consume the same
  runtime instead of creating a second agent path

## Decision

Rebuild Pico from a clean `main`-based line around a Maka-style runtime kernel.

The new architecture will introduce:

- a dedicated runtime-kernel boundary for `RuntimeRunner`,
  `InvocationContext`, `AgentFlow`, `ToolRuntime`, `ModelAdapter`,
  `RuntimeEventLedger`, `ProjectionManager`, and recovery. The target shape can
  become `pico/runtime`, but the first `main`-based slice may use a transitional
  module such as `pico/runtime_kernel.py` because `main` already has a legacy
  `pico/runtime.py` module.
- `pico/headless` for fixed-prompt task runs, task-run WAL, protected verifier
  boundaries, result export, runtime-policy A/B, and prompt optimization.
- `pico.cli` as a thin adapter that builds runtime requests and delegates to the
  shared kernel.
- `pico/core` as legacy compatibility during rollout, not the home for new
  runtime work.

`RuntimeEvent` is the source of truth for the whole product. Session history,
CLI output, desktop timelines, trace files, reports, telemetry, and task-run
exports are projections.

## Alternatives Considered

### Continue patching v3

Rejected. v3 contains useful experiments, but its runtime center is already too
tangled for the new objective. Patching it would preserve the same source-of-truth
confusion.

### Attach Maka as an external harness

Rejected. This would improve measurement but would not fix Pico's own runtime.
The goal is a Python-native runtime, not an external controller around a weak
runtime.

### Build a benchmark-only Pico

Rejected. Pico's product core is a local code-agent runtime. Headless evaluation
is a first-class lab capability, not the whole product.

### Immediately switch all commands to the new runtime

Rejected. The new kernel should run beside legacy until it passes fake-provider
tests and live-provider acceptance for a no-tool final case, a read-only tool
case, runtime-event-driven projections, normalized provider metadata, and a
headless single-task run.

## Consequences

- New implementation work should land in the new runtime-kernel boundary or
  `pico/headless`, not in `pico/core`.
- The first implementation slices should be vertical runtime-spine slices, not
  horizontal layer rewrites.
- The first tool surface is read-only: read file, list files, and search text.
- Provider hardening focuses on `ModelAdapter` normalization while keeping text
  input/output for the first runtime replacement.
- Provider-native tool calling, write/edit/shell tools, advanced memory/context
  policies, desktop UI, runtime-policy A/B, and prompt optimization are later
  slices.
- Fake-provider tests are the automated regression gate; live-provider runs are
  the real acceptance gate.
