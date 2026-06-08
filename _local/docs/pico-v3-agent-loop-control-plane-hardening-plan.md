# Pico v3 Agent Loop Control Plane Hardening Plan

Date: 2026-06-08

Branch: `codex/v3-agent-loop-control-plane`

Base commit: `4eba436 Implement agent loop control plane`

Status: implementation plan

## Goal

Harden the new agent-loop control plane before treating it as merge-ready. The
core architecture stays the same: keep `Engine.run_turn()` as a readable
generator loop, and make runtime decisions auditable through trace events,
runtime consumers, `TaskState.evidence_summaries`, report output, and final
readiness.

## Accepted Review Findings

1. Runtime consumer failures must not silently hide evidence-summary errors.
2. `run_shell` structured status should be parsed from the full tool result, not
   a rendered/clipped projection.
3. Tool-result artifact refs must not assume the run store lives under the
   workspace root.
4. `verification_signal` currently overstates `covers_changed_paths`.
5. Strict final readiness blocks too many soft reasons.
6. Partial-success workspace changes need a hard readiness reason.
7. Artifact storage and prompt microcompact need clearer boundaries and tests.
8. Stream golden tests need more edge-path coverage.

## Rejected Or Downgraded Findings

The claim that current `run_shell` exit-code parsing is broken by long stdout is
not true for Pico's current `tool_run_shell()` output, because `exit_code:` is
emitted before stdout and stderr. The implementation will still be hardened so
future result renderers cannot create this bug.

## Non-Goals

- Do not add Langfuse in this hardening pass.
- Do not rewrite the engine as a formal state machine.
- Do not make report generation parse `trace.jsonl`.
- Do not make final readiness depend on report generation or external sinks.
- Do not touch unrelated local `_local/benchmark`, `_local/research`,
  `examples`, or release asset files.

## Phase 1: Evidence Pipeline And Tool Result Hardening

Acceptance:

- Duplicate terminal loop transitions create visible consumer error evidence.
- Normal runs do not report consumer errors.
- `run_shell` status is parsed from full tool output before artifact rendering.
- External run-store artifact paths do not raise `ValueError`.

## Phase 2: Verification Signal Semantics

Acceptance:

- Verification commands are classified by command shape, not raw substring.
- Obvious false positives such as `echo pytest` are not verification.
- Common commands such as `npm run test`, `pnpm run build`, `yarn test`, `tox`,
  `go test`, `cargo test`, and `make test` are recognized.
- `covers_changed_paths` no longer claims coverage without proof.
- Reports expose enough fields to explain the signal honestly.

## Phase 3: Final Readiness Risk Levels

Acceptance:

- Strict mode blocks hard reasons only.
- Context pressure alone does not strict-block a final answer.
- Current-run high-priority todo alone does not strict-block a final answer.
- Failed verification and partial-success workspace changes strict-block.
- Soft mode still deduplicates reminders by reason signature.

## Phase 4: Artifact And Microcompact Recoverability

Acceptance:

- Full long tool output is recoverable by artifact ref and sha256.
- Prompt rendering does not mutate `session["history"]`.
- Recent long outputs are not stubbed.
- Last failed and last workspace-changing tool results are not stubbed.
- Older results tied to current changed paths are not stubbed.

## Phase 5: Stream And Transition Edge Coverage

Acceptance:

- Provider retry, parse retry, plan notice, strict final gate, retry limit, and
  step-limit paths have stream/transition coverage.
- Multi-tool transitions distinguish requested and executed tool counts.
- User-visible stream event ordering remains stable.

## Verification

Focused checks after each phase:

```bash
uv run pytest tests/test_engine_acceptance.py tests/test_tool_policy_acceptance.py tests/test_final_readiness.py tests/test_turn_transitions.py tests/test_architecture_boundaries.py -q
uv run ruff check pico tests scripts
git diff --check
```

Final checks:

```bash
uv run pytest tests -q
uv run ruff check pico tests scripts
git diff --check
```
