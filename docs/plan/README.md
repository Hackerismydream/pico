# Pico planning model

This directory explains how Pico planning artifacts relate. It is not a second
issue tracker.

## Authorities

1. [GitHub Issue #1](https://github.com/Hackerismydream/pico-harness/issues/1)
   is the approved Pico v1 product contract.
2. Open delivery issues are the source of truth for scope, acceptance criteria,
   dependencies, and required Gates.
3. [roadmap.md](../roadmap.md) is the reader-oriented dependency map and future
   narrative. It must summarize, not silently override, issue bodies.
4. [project-status.md](../project-status.md) records current implementation and
   evidence boundaries.
5. [evolution.md](../evolution.md) records completed slices after they land on
   `main`.

An unchecked checkbox in a closed issue is not the evidence source. The merged
PR, commit-bound Gate output, and retained verifier own that evidence.

## Status vocabulary

| Label | Meaning |
| --- | --- |
| Contracted | Accepted in Issue #1 or an open delivery issue |
| Implemented | Present in current code |
| Deterministically verified | Passed without external services or live model/channel claims |
| Live verified | Passed against the named real external resource, with a commit-bound artifact |
| Historical evidence | Valid for an older commit or donor checkout only |
| Proposed | A future option without an accepted delivery issue |
| Blocked | A required dependency or authority is absent |

Do not collapse these labels into a single “done” state.

## Current delivery graph

```text
Issue #21 real Feishu V-LF passed

Issue #70 CodeCairn M2/M4/M5 completed

Issue #24 real small-real verdict
  -> full V-R0
  -> version, tag, release
```

Issue #22 was closed by PR #50. Issue #23 was closed by PR #51. Issue #21
closed after its required real V-LF run. The V-R0 driver and small-real
deterministic harness are implemented, but the real small-real verdict and
complete release Gate remain open. See [roadmap.md](../roadmap.md) for scope
and Gates.

The separate Pico Harness v0.1 portfolio milestone is complete. The accepted
Pico Harness v0.2 implementation has replaced active EverOS product coupling
with CodeCairn Memory and completed joint verification; neither milestone
label sets package semver. GitHub Issue
[#65](https://github.com/Hackerismydream/pico-harness/issues/65) authorizes
the Pico-owned `codecairn-001` and `codecairn-002` sequence at CNY 0, and
Issue [#70](https://github.com/Hackerismydream/pico-harness/issues/70)
completed `codecairn-003`:

```text
CodeCairn v02-001 importer
  -> CodeCairn v02-002 Adapter
     -> Pico codecairn-001
        -> Pico codecairn-002
           -> Pico codecairn-003
              -> CodeCairn v02-003 evidence state-sync
```

## Adding work

Create or update a GitHub issue when the proposal changes product behavior,
acceptance evidence, release scope, or a cross-module contract. A local design
document may explore implementation, but it does not authorize the work by
itself.

Future ideas belong in the “Future candidates” section of
[roadmap.md](../roadmap.md) until accepted. When accepted, link the new issue,
define dependencies and Gates, and move the item into the committed roadmap.

The proposed
[TokenWise evidence expansion](analysis/tokenwise-evidence-expansion.md)
records the current CV-eligible DeepSeek result and a larger 320-Trial
follow-up. It is analysis only and does not authorize implementation or paid
Provider calls.

## Accepted delivery packages

The following package is accepted under GitHub Issue
[#59](https://github.com/Hackerismydream/pico-harness/issues/59):

| Package | Architecture contract | Delivery analysis | Tasks |
| --- | --- | --- | --- |
| PicoBench Ship-1 | [Agent application evaluation](../evaluation/README.md) and [Ship-1 contract](../evaluation/picobench-ship-1.md) | [Ship-1 analysis](analysis/picobench-ship-1.md) | [picobench-001 through picobench-008](tasks/README.md) |
| CodeCairn Pico implementation | [CodeCairn backend contract](../specs/codecairn-memory-backend.md) | [replacement analysis](analysis/codecairn-memory-replacement.md) | [codecairn-001 and codecairn-002](tasks/README.md) |

PicoBench Ship-1 measures Runtime, Context, Memory/Skill, Tool/MCP, and Agent
task outcomes. Issue #59 fixed the Provider/model selection boundary, CNY 100
cost ceiling, allowed product-side Context seam, and task range. Ship-1 does
not close Issue #24 or V-R0 and does not provide recovery evidence.

## Executed joint evidence package

The following joint evidence package completed under GitHub Issue
[#70](https://github.com/Hackerismydream/pico-harness/issues/70):

| Package | Architecture contract | Delivery analysis | Tasks |
| --- | --- | --- | --- |
| CodeCairn joint evidence | [CodeCairn backend contract](../specs/codecairn-memory-backend.md) | [replacement analysis](analysis/codecairn-memory-replacement.md) | [codecairn-003](tasks/codecairn-003.md) |

Issue #65 fixed the compatible CodeCairn identity and authorized the two Pico
implementation deliveries. Issue #70 owned and completed the joint installed
and paired-evidence task under one cumulative CNY 100 hard ceiling. Its formal
experiment completed 32/32 Trials and 16/16 valid Pairs. The measurement is
valid but its positive claim is ineligible because CodeCairn returned three
memories for every hard-negative query.

The completed execution Goal for this package is
[`pico-codecairn-joint-evidence-goal.md`](pico-codecairn-joint-evidence-goal.md).
It records the immutable handoffs, credential-free installed Gate, paid
Provider campaign, independent Claim Gate, and final handoff.

## Accepted PicoBench task-effect v2

[`picobench-task-effect-v2-goal.md`](picobench-task-effect-v2-goal.md) defines
the checkout-only successor campaign accepted by GitHub Issue
[#77](https://github.com/Hackerismydream/pico-harness/issues/77). It preserves the completed
continuity tracer but requires Memory-off tasks to remain independently
solvable, expands retrieval negatives and stale/conflict coverage, and
separates task-success claims from rediscovery-efficiency claims.

Stage A implemented the credential-free task, fixture, Verifier, Pack,
reducer, report, regression, and smoke contracts. Issue #79 then bound the
installed Pico and CodeCairn wheels, Stage C digest, Provider contract, and a
30 CNY cumulative hard ceiling. Its final calibration completed 12/12 task
Trials and 10/10 retrieval cases, but all task Trials were Provider failures
and 0/6 Pairs were valid. The measurement and every Claim Gate are ineligible,
so the formal matrix did not run. The campaign charged 1.29966592 CNY and the
paid authority is no longer active.

This result does not set Pico package semver, update the CodeCairn product pin,
alter the release graph, or establish task-effect uplift. See the
[operator contract](../evaluation/picobench-task-effect-v2.md) for the exact
evidence boundary.

The executable Codex Goal for the Pico-owned implementation sequence is
[`pico-codecairn-implementation-goal.md`](pico-codecairn-implementation-goal.md).
It consumed the exact CodeCairn `v02-002` wheel handoff, landed
`codecairn-001` before `codecairn-002`, and stopped before the joint
`codecairn-003` paid-evidence scope.
