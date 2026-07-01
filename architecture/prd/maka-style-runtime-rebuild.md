# PRD: Maka-Style Pico Runtime Rebuild

## Problem Statement

Pico is meant to be a Python local code-agent runtime with built-in headless
evaluation, but the current runtime shape does not support that story cleanly.
Runtime execution, session history, prompt construction, tool handling,
reporting, evaluation, and recovery are too tightly coupled. This makes Pico hard
to explain, hard to test, hard to recover, and hard to improve with credible
runtime-policy A/B or prompt optimization.

The user wants Pico to move closer to Maka's architecture: a local code-agent
runtime where CLI, desktop, and headless evaluation are entrypoint adapters over
one shared runtime kernel, and where runtime events are the product-wide source
of truth.

## Solution

Rebuild Pico from a clean `main`-based line around a Maka-style runtime kernel.

The new Pico will keep the `pico` CLI as the user-facing entrypoint, but the CLI
will become a thin adapter over a shared runtime kernel. The same kernel will
also power future desktop and headless evaluation surfaces.

The runtime kernel will emit canonical `RuntimeEvent` facts. Session history,
CLI output, desktop timelines, trace files, reports, telemetry, and task-run
exports will be projections from those runtime events. Headless evaluation will
consume the same runtime instead of using a separate agent path.

## User Stories

1. As a Pico user, I want `pico` to remain the main command, so that I do not need to learn a different entrypoint for the rebuilt runtime.
2. As a Pico user, I want to choose between legacy and kernel runtimes during rollout, so that I can compare behavior and recover if the new runtime fails.
3. As a Pico user, I want one-shot requests to run through the new runtime kernel, so that normal usage benefits from the rebuilt architecture.
4. As a Pico user, I want REPL usage to eventually run through the same runtime kernel, so that interactive and one-shot behavior do not diverge.
5. As a Pico user, I want runtime failures to be classified clearly, so that I know whether the issue was provider, tool, permission, runtime, or benchmark related.
6. As a Pico user, I want real provider runs to record normalized provider metadata, so that reports can explain which provider/model/finish reason/usage path was used.
7. As a Pico user, I want read-only tool use to be visible and auditable, so that I can trust what the agent inspected before answering.
8. As a Pico user, I want large tool results to become artifacts rather than polluting the prompt, so that model history stays bounded and reports remain inspectable.
9. As a Pico maintainer, I want `RuntimeEvent` to be the source of truth, so that session history, reports, traces, and UI projections do not become competing databases.
10. As a Pico maintainer, I want session history to be a projection, so that prompt history and runtime recovery do not depend on user-visible transcript text.
11. As a Pico maintainer, I want a `ModelHistoryProjector`, so that the next model input is an explicit and testable policy over runtime events.
12. As a Pico maintainer, I want a `ModelAdapter`, so that OpenAI-compatible, Anthropic-compatible, and DeepSeek-style profiles share normalized model results and errors.
13. As a Pico maintainer, I want provider hardening without immediate provider-native tools, so that the first runtime replacement stays scoped.
14. As a Pico maintainer, I want a `ToolRuntime`, so that validation, permissions, execution, artifacts, telemetry, and failure classification live in one boundary.
15. As a Pico maintainer, I want permission requests to be runtime events, so that CLI, desktop, and headless eval share one permission model.
16. As a Pico maintainer, I want headless eval to treat agents as untrusted by default, so that prompt optimization cannot reward hack the workspace or verifier.
17. As a Pico maintainer, I want protected verifier boundaries, so that benchmark pass/fail is not controlled by files the agent can forge.
18. As a Pico maintainer, I want infrastructure failures separated from benchmark failures, so that evaluation results remain honest.
19. As a Pico maintainer, I want model self-checks separated from official verifier results, so that confident final answers do not become benchmark passes.
20. As a Pico maintainer, I want long-task progress surfaces to stay thin, so that the model does engineering work instead of maintaining a proof chain.
21. As a Pico maintainer, I want fake-provider tests for every first-slice behavior, so that CI can validate the runtime without real model calls.
22. As a Pico maintainer, I want live-provider acceptance gates, so that the rebuilt runtime is proven against real models before becoming the default.
23. As a Pico maintainer, I want the first runtime slice to include both no-tool and read-only-tool cases, so that the runtime proves it is more than a chat wrapper.
24. As a Pico maintainer, I want the first tool surface limited to read file, list files, and search text, so that the runtime spine can be proven before write or shell tools increase risk.
25. As a Pico maintainer, I want advanced context and memory policies delayed, so that the runtime kernel can stabilize before higher-level policies attach to it.
26. As a Pico maintainer, I want new runtime work in `pico/runtime`, so that the new kernel does not disappear inside legacy `pico/core`.
27. As a Pico maintainer, I want headless lab work in `pico/headless`, so that evaluation and prompt optimization stay separate from interactive runtime logic.
28. As a Pico maintainer, I want old `pico/core` treated as legacy, so that new features do not extend the old runtime center.
29. As a Pico maintainer, I want the desktop product to be a projection shell, so that desktop does not become a second runtime.
30. As a Pico maintainer, I want task-run exports to be projections from runtime facts, so that headless evaluation and normal runs share a single audit trail.
31. As a Pico maintainer, I want runtime-policy A/B to run against the same kernel, so that pruning, continuation, and context policies can be evaluated honestly.
32. As a Pico maintainer, I want prompt optimization to be built after the runtime baseline is stable, so that prompt search is not optimizing a broken execution substrate.
33. As a resume reviewer, I want Pico's architecture to have clear runtime/kernel/evaluation boundaries, so that the project can be explained as agent infrastructure rather than a demo chatbot.
34. As a resume reviewer, I want live-provider evidence and report artifacts, so that claims about the runtime are backed by real acceptance data.
35. As a future contributor, I want Maka-aligned terminology, so that Maka docs and Pico Python modules map cleanly during implementation and review.

## Implementation Decisions

- Start from a clean `main`-based branch.
- Preserve `pico` as the primary CLI entrypoint.
- Add a runtime switch during rollout so legacy and kernel runtime behavior can be compared.
- Treat `RuntimeEvent` as the canonical product-wide source of truth.
- Treat session history as a user-visible conversation projection, not the runtime database.
- Add a `ModelHistoryProjector` to produce the next model input from runtime events.
- Add a `ModelAdapter` to normalize model text, usage, finish reason, metadata, and provider errors.
- Keep first-stage provider I/O text-based; provider-native tool calling is a later flow.
- Add `ToolRuntime` as the lifecycle boundary for tool validation, permissions, execution, artifacts, telemetry, and tool failure classification.
- Represent permission requests and decisions as runtime events.
- Add a runtime-kernel boundary for `RuntimeRunner`, `InvocationContext`, `AgentFlow`, `ToolRuntime`, `ModelAdapter`, `RuntimeEventLedger`, projection, and recovery concepts. The target can become a package, but the first slice may use a transitional module because `main` already has a legacy `pico/runtime.py`.
- Add a headless package for fixed-prompt task runs, task-run WAL, verifier boundary, result export, runtime-policy A/B, and prompt optimization.
- Keep legacy core as a compatibility adapter during rollout, not as the destination for new runtime work.
- Implement vertical runtime-spine slices instead of horizontal half-finished layers.
- The first runtime slice must include a no-tool final-answer case and a read-only tool case.
- The first tool surface is read-only: read file, list files, and search text.
- Advanced context compaction, durable memory, retrieval, long-session handoff, write/edit/shell tools, subagents, plan mode, todos, desktop UI, runtime-policy A/B, and prompt optimization are later slices.
- Headless evaluation treats the agent/config under test as untrusted by default.
- Official verifier results remain distinct from model self-checks and runtime completion.
- Desktop, when built, is a projection shell and request source over the same runtime kernel.

## Testing Decisions

- Use the highest seam first: the `pico` CLI with a runtime switch should exercise the kernel path end to end.
- Automated tests use fake providers to prove deterministic runtime behavior without external model calls.
- Live-provider acceptance is required before the kernel runtime becomes the default.
- The first no-tool test proves `RuntimeRunner`, `ModelAdapter`, runtime-event ledger writes, and projections.
- The first read-only tool test proves agent-flow parsing, `ToolRuntime`, runtime-event recording, model-history projection, and finalization.
- Projection tests should assert external behavior: CLI output, session history, trace/report artifacts, and task-run export are derived from runtime events.
- Provider tests should use fake transports for OpenAI-compatible, Anthropic-compatible, and DeepSeek-style profiles where possible.
- Permission tests should prove CLI/headless behavior consumes the same permission events rather than bypassing runtime permission semantics.
- Headless tests should prove protected verifier paths, infrastructure-vs-benchmark failure separation, and task-run export.
- Live acceptance should include at least one no-tool real model run and one read-only tool real model run.
- Existing Pico tests can be mined for useful behavioral expectations, but the new runtime should not treat v3 internals as the target architecture.

## Out of Scope

- Reusing Maka as an external controller around Pico.
- Rebuilding the full desktop product in the first runtime slice.
- Provider-native tool calling in the first runtime slice.
- Write, edit, shell, subagent, memory, plan mode, and todo tools in the first runtime slice.
- Prompt candidate optimization before the runtime baseline is stable.
- Runtime-policy A/B before the kernel can run no-tool and read-only-tool paths.
- Migrating v3 memory/context internals as a starting assumption.
- Treating model self-check or final answer as official benchmark pass/fail.

## Further Notes

- The accepted architecture decision is recorded in ADR 0001.
- The current domain glossary defines Pico as a local code-agent runtime, not a benchmark-only tool.
- Maka is the reference shape for architecture boundaries and terminology, but Pico should be a Python-native implementation.
- The first success condition is not prompt-performance improvement; it is one inspectable runtime truth that can drive CLI output, reports, recovery, and evaluation artifacts.
