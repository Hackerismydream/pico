---
id: picobench-006
scope: evaluation
status: completed
depends-on:
  - picobench-002
authority-issue: 59
gates: [G3, G4, G5]
requires-live-provider: false
---

# PicoBench Tool and MCP Task Pack

## Objective

Measure whether progressive Tool disclosure reduces model-visible Tool Schema
cost without degrading verified task completion or Tool-call quality.

## Context

A Python fake validates Tool contracts but does not support an MCP claim. The
formal Pack must traverse a real supported local MCP transport while keeping
the underlying Tool catalog identical in both variants.

Owned paths:

```text
benchmarks/picobench/packs/tool_mcp/
benchmarks/picobench/tasks/tool_mcp/
benchmarks/picobench/fixtures/mcp/
tests/test_picobench_tool_mcp_track.py
tests/integration/test_picobench_mcp_e2e.py
```

## Path

1. Implement a deterministic local MCP fixture with exactly 64 intentionally
   similar Tool names, descriptions, and parameter shapes so the catalog
   exceeds the current default Tool Search threshold of 50.
2. Freeze eight tasks that require one to three specific Tools and terminate in
   independently verifiable state.
3. Compare all Tools visible with progressive disclosure while holding the MCP
   catalog, Tool implementations, Context, Memory, model, budget, and retries
   constant.
4. Estimate Tool Schema tokens from every actual main-Agent `tools` payload
   sent to the Provider with one digest-bound tokenizer; report per-call and
   Trial-total values.
5. Record meta-Tool calls separately from normalized target calls. Map a
   control direct call and a treatment `tool_call` envelope to the same
   `TargetCallRecord` shape; preserve invalid envelopes, unknown targets,
   target validation failures, direct-hidden calls, nested Registry results,
   and MCP receipts.
6. Define first-target accuracy over the first normalized target attempt and
   an exact repeat over target Tool name plus canonical JSON target arguments
   across the complete Trial. Meta calls do not enter target-call denominators.
7. Verify MCP transport startup, registration, calls, receipts, and teardown in
   both variants. A deterministic smoke must complete
   `tool_search -> tool_call -> MCP receipt`.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_tool_mcp_track.py -q
uv run pytest tests/integration/test_picobench_mcp_e2e.py -q
```

Acceptance:

- every formal task crosses a real local MCP transport;
- both variants expose the same underlying Tool implementations;
- the initial model-visible Tool sets differ and treatment meta-Tools are
  connected; actual meta-Tool invocation is an outcome, not an integrity Gate;
- deterministic smoke proves `tool_search -> tool_call -> MCP receipt`;
- positive efficiency eligibility uses at least six tasks with two
  success-matched usage-complete Pairs, the contract's equal-task formula, and
  at least 50 percent Schema-token reduction;
- treatment pass count is not below control, and normalized invalid-target and
  exact-target-repeat rates do not worsen;
- null target-call rates make the positive Tool claim indeterminate;
- no task loses two of three verifier passes;
- claims of reduced invalid or repeated calls require their own preregistered
  positive threshold;
- no Tool Schema estimate is described as Provider-billed Tool tokens.
