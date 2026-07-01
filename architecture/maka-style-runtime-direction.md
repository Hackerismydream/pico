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

## Project Goal

Pico's goal is to become a resume-grade local code-agent runtime, not another
thin chat CLI. The project should prove that a coding agent can be run,
inspected, evaluated, and improved from one shared runtime substrate.

The target product is:

- a local coding-agent harness that can execute repository-grounded tasks
- a runtime kernel that owns model calls, tool calls, permissions, failure
  classification, and terminal status
- a canonical RuntimeEvent ledger that records what actually happened
- projections that turn runtime facts into CLI output, sessions, traces,
  reports, desktop timelines, and headless task exports
- a headless lab that can run fake-provider regression, real-model acceptance,
  runtime-policy A/B, and prompt optimization against the same runtime

The immediate objective is not to win a benchmark by prompt tricks. The
objective is to replace Pico's weak runtime with an inspectable, testable,
recoverable kernel so every future capability has a stable place to attach.

This is why Maka runtime parity comes before new experiments. Pico v3 already
proved the failure mode: if the runtime cannot produce trustworthy execution
facts, resume-safe runs, independent verifier evidence, and failure taxonomy,
then tool-use experiments and prompt-tuning experiments become decorative output
rather than engineering evidence. The next work must therefore rebuild the
runtime/control-plane substrate first, then use tool calling and system-prompt
optimization as validation workloads.

The first prompt-optimization bridge should stay narrow: explicit candidates may
be accepted or rejected by verifier-backed score improvement over a declared
baseline, but Pico should not generate prompt candidates automatically until the
artifact contract, resume behavior, and live-provider acceptance gates stay
stable under this simpler policy.

## Why Maka-Like

Maka is the right reference shape because it is solving the same product
problem: a local code-agent harness whose value comes from runtime control,
evaluation evidence, and artifact inspection. Pico should be Maka-like at the
architecture boundary level, not by wrapping Maka as an external dependency and
not by copying surface UI details.

The Maka-like direction reduces development friction because it gives Pico a
known-good decomposition:

- entrypoints are adapters, not separate runtimes
- the runtime kernel is the execution authority
- runtime events are the source of truth
- sessions, reports, traces, desktop views, and task exports are projections
- evaluation is built into the runtime lifecycle instead of bolted on later
- real-provider acceptance gates complement deterministic fake-provider tests

This matters because Pico's old runtime failed at the substrate level. Adding
more benchmark scripts, prompts, memory features, or UI surfaces on top of that
substrate would keep producing impressive-looking artifacts without making the
agent reliable. A Maka-like runtime forces the project to answer the hard
engineering questions first: what happened, who produced it, how it is ordered,
how it is replayed, how it failed, and how a real model run proves the path.

The intended result is still Pico: a Python-native implementation with Pico's
CLI, headless lab, provider setup, and future desktop shell. Maka supplies the
architecture target and vocabulary; Pico owns the implementation and product
shape.

## Source Of Conviction

The Maka-like direction is not based on generic taste for agent frameworks. It
comes from specific Maka PRs and experiments that made the runtime-lab shape
feel worth copying into Pico.

Maka PR #340, `feat(headless): validate active-prune 2048`, is the main runtime
policy example. It combines runtime replay fixes, Harbor continuation recovery,
A/B pair concurrency, active tool-result pruning, and a benchmark-backed
non-inferiority report. The important part is not the exact 2048-token policy.
The important part is the engineering shape: a runtime policy is changed only
with artifact-backed evidence, cost/token accounting, failure classification,
and regression tests. The PR reports a combined evidence set, separates old and
continuation-rescue strata, and states the claim narrowly as no large regression
detected under the declared margin rather than pretending to prove losslessness.

The second source is Jakevin's tweet about Maka's prompt optimization loop:
https://x.com/jakevin7/status/2068354579251782068. The tweet describes four PRs
that turn system-prompt writing into a benchmark-feedback optimization loop:

- PR #67 adds the fixed-prompt WAL controller. Candidate prompt experiments are
  recorded in an append-only log, runs can resume, and infra failures are kept
  separate from benchmark failures.
- PR #68 adds the prompt candidate loop. The agent generates multiple system
  prompt variants, runs them through Harbor against real Terminal Bench tasks,
  and receives verifier reward.
- PR #69 adds the acceptance policy. A prompt is accepted only when benchmark
  score improves; agent self-judgment is not enough.
- PR #70 hardens prompt identity. Prompt hashes are written into trajectories and
  checked by the controller so a run is tied to the candidate prompt actually
  under test.

These examples are why Pico's target is a runtime lab, not just a better CLI
loop. The attractive property is the discipline: append-only experiment logs,
resume-safe controllers, independent verifiers, explicit acceptance policies,
prompt/runtime-policy identity, and honest separation of infrastructure failure
from agent-performance failure. That is the part Pico should translate into
Python.

For planning, this also defines the first proof of progress. Pico does not need
to prove immediately that its prompts beat Maka's prompts. It first needs to
prove that the same class of experiment can be run honestly: a real provider can
run through the shared kernel, every run is tied to the runtime/prompt identity
under test, artifacts can be replayed, infra failures are excluded from benchmark
score, verifier results are independent, and a failed run can be resumed or
reconciled without throwing away previous evidence.

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
