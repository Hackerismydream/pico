---
id: picobench-002
scope: evaluation
status: completed
depends-on:
  - picobench-001
authority-issue: 59
gates: [G1, G4]
requires-live-provider: false
---

# PicoBench Trial Host and observation seams

This completed task card records the historical pre-CodeCairn Runtime.

## Objective

Run one isolated Trial through Pico's real Runtime composition, capture complete
Trial evidence, and execute a parent-owned deterministic Verifier.

## Context

PinchBench Direct calls `AgentLoop.run_turn()` directly and cannot prove Spine,
Lane, Runtime Assembly, Session, or Delivery behavior. The current Agent Loop
also constructs its Context Engine internally, so single-axis Context, user
Memory, and Skill variants need one narrow construction seam. Any `pico/`
change requires explicit authorization in the accepted delivery issue.
Without authorization for the exact product paths below, this task is
`blocked`; mutating `AgentLoop.context_engine` after construction is not an
accepted fallback.

Owned paths:

```text
benchmarks/picobench/host.py
benchmarks/picobench/isolation.py
benchmarks/picobench/recorder.py
benchmarks/picobench/usage.py
benchmarks/picobench/verifier.py
tests/test_picobench_trial_host.py
tests/integration/test_picobench_runtime_smoke.py
```

Required authorized product paths:

```text
pico/agent/loop/main.py
pico/cli/_runtime_assembly.py
pico/context_engine/factory.py
tests/test_cli_runtime_assembly.py
tests/test_default_context_engine.py
tests/test_runtime_host_contracts.py
```

## Path

1. Launch each Trial in a child process with an isolated workspace,
   `PICO_HOME`, EverOS root, Session identity, trace root, MCP lifecycle, and
   evidence directory.
2. Boot through `assemble_runtime`, start the owned backend, construct
   `AgentTurnRunner`, Scheduler, DeliveryHub, and a benchmark-owned
   `RecordingOutlet`, then submit through Spine.
3. Add only an optional `context_engine_factory` construction seam threaded
   from `assemble_runtime` into `AgentLoop`. Its default calls the current
   `build_context_engine`; PicoBench may supply a factory that swaps declared
   `SegmentBuilder` and Skill-source adapters without mutating private fields.
   The product seam is generic and never imports PicoBench.
4. Keep the same real backend when disabling user-track Memory recall so
   EverOS Skill availability does not change.
5. Wrap Provider and Memory/Skill adapters to capture per-call usage and
   anonymous selection observations without changing their returned values.
6. Run the Verifier in the parent after Runtime teardown. Do not expose its
   code or expected data in the workspace, prompt, or Tool definitions.
7. Digest-check the Verifier before and after the Trial. Under host execution,
   describe this as tamper evidence, not an inaccessible security boundary.
8. Guarantee one terminal Attempt Record for normal completion, task timeout,
   Provider failure, infrastructure failure, cancellation, and child-process
   death; the parent derives the Trial summary after Comparison Block
   resolution.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_trial_host.py -q
uv run pytest tests/integration/test_picobench_runtime_smoke.py -q
```

Acceptance:

- the full-path host never calls `AgentLoop.run_turn()` directly;
- default CLI, TUI, and Gateway Runtime construction is unchanged by the
  optional experiment seam;
- each Trial state root is isolated from every other Trial;
- usage records every attributable model call and marks unknown usage as
  unknown rather than zero;
- a changed or crashing Verifier is an infrastructure failure;
- timeout or process death still produces a parseable terminal record;
- teardown leaves no open backend, MCP process, Scheduler, or Delivery worker;
- delivered, injected-delivery-failure, and no-outlet scenarios are observable
  only after the DeliveryHub reaches idle.
