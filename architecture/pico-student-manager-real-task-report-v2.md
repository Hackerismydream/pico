# Pico real task evaluation: student management system

Date: 2026-05-09
Branch: `codex/pico-v4-runtime-harness`

## Goal

Use Pico itself to build a small but real full-stack project:

- FastAPI backend
- CRUD API for `id`, `name`, `age`, `grade`
- JSON file persistence
- native HTML/CSS/JS frontend for list/create/edit/delete
- README startup instructions
- real verification proving backend route and frontend API path alignment

This is intentionally not a benchmark template. It tests whether Pico can close a multi-file coding task through planning, implementation, verification, repair, and finalization.

## What changed in Pico

The latest iteration keeps the generic completion-control pieces but changes their role from hard gates to runtime assessment and reminders:

- `todo_write` now preserves the original `started_changed_path_count` for an existing in-progress task, so rewriting the task ledger cannot erase file-change evidence.
- Completion assessment records missing verification, open tasks, and weak evidence in report/trace without blocking the final answer.
- Runtime progress pressure is emitted as `runtime_reminder_emitted`, so tools still run while the model receives concrete next-action pressure.
- `todo_write` / `todo_update` keep task-ledger structure valid, but quality concerns such as "completed without file evidence" are warnings rather than rejected tool calls.
- Pico no longer hard-codes FastAPI, frontend API smoke commands, route names, or static asset checks into runtime completion.
- Stack-specific checks should be produced by a generic verifier/planner from the current artifact graph, not embedded as one-off completion rules.

## Evaluation runs

### Run v2

Workspace:

`/tmp/pico-student-manager-live-20260509-v2`

Run:

`run_20260509-011521-bfe46d`

Result:

- Pico wrote backend files and later partial frontend/docs.
- Runtime blocked early final answers because open tasks remained and API smoke evidence was missing.
- It hit the step limit before completion.

Root cause:

`todo_write` reset the in-progress task's starting evidence count after files had already been written. Pico then tried to mark the frontend task complete, but runtime rejected it because the rewritten task appeared to have no new file evidence.

Fix:

Preserve existing in-progress task metadata across `todo_write`.

### Run v3

Workspace:

`/tmp/pico-student-manager-live-20260509-v3`

Run:

`run_20260509-012328-00509f`

Pico status:

- `status=completed`
- `stop_reason=final_answer_returned`
- all 5 tasks completed

Independent smoke result:

Failed. Importing the FastAPI app raised:

`AssertionError: Status code 204 must not have a response body`

Root cause:

Pico's verification was still too weak. It parsed route decorators and checked that frontend code contained `/api/students`, but it did not instantiate FastAPI or hit a route. The runtime incorrectly accepted the word `uvicorn` in README validation as API smoke evidence.

Fix:

Remove `uvicorn` as a standalone smoke marker. API smoke now requires `TestClient`, `httpx`, `requests`, `curl`, or explicit `client.get/post/put/delete(...)` style evidence.

### Run v4

Workspace:

`/tmp/pico-student-manager-live-20260509-v4`

Result:

The OpenAI-compatible provider stopped with:

`HTTP 403: API Key额度不足`

This run is not a Pico completion failure; it is a provider quota failure after the runtime changes were applied.

### Provider fallback checks

- `anthropic-sdk`: local dependency missing (`anthropic` package not installed).
- `anthropic`: provider returned HTTP 403.
- `deepseek`: ran but did not converge in a useful way; it repeatedly tried to overwrite an existing `static/index.html` with `write_file` without first reading it, and was blocked by the prior-read policy.

The DeepSeek run is useful as a failure sample: weaker model/tool discipline makes runtime intervention more important, but it is not a clean success/failure signal for the OpenAI-compatible path.

## Current conclusion

Pico is stronger than before, but I would not yet claim it can reliably complete this class of project independently.

What is now working:

- It records task state, completion assessment, trace, and verification artifacts.
- It can detect open tasks and weak verification without turning those signals into benchmark-specific hard constraints.
- It can emit progress reminders for missing todo ledgers, stale task status, missing file evidence, and read-heavy loops while still allowing tools to execute.
- It no longer accepts route parsing or README checks as a special API-smoke category because stack-specific smoke checks are outside core runtime.

What is still not proven:

- A fresh full run after the generic assessment/reminder change has not passed, because current providers failed or stalled.
- The runtime still depends too much on the model choosing the right next action after a precise reminder.
- There is no deterministic verifier driver that can run the suggested smoke itself and feed a compact failure reason back to the model.

## Claude Code comparison

The Claude Code source research points to a stronger pattern than simple final gating:

- tool-use events are first-class runtime events, not just chat text;
- permission/tool policies are stateful and visible to the UI;
- hooks can verify or block behavior around tool use;
- task/session state is durable enough for recovery and remote/session adapters;
- UI surfaces task/tool progress instead of hiding the control loop.

The lesson for Pico is that completion should be a control-plane problem, not a prompt discipline problem. The runtime should detect the current artifact graph, choose the next required pressure, and produce concrete tool-level interventions.

## Next engineering step

Add a deterministic `VerifierDriver` as a strategy layer, still without adding an external service:

- infer project type, available test commands, startup commands, and likely integration checks from files;
- generate and run the best available verification command for that artifact graph;
- record the result as `VerificationArtifact`;
- if it fails, move stage to `repairing` and feed the exact compact failure reason back to the model;
- keep final answers allowed, but report `incomplete` or `unverified` when verification is missing or failing.

This is the missing piece between "Pico can honestly report what happened" and "Pico can reliably complete the project".

## Verification of Pico changes

Code-level verification:

- `uv run ruff check .`
- `uv run python -m pytest -q`

The focused completion-controller suite also covers:

- stack-specific FastAPI/frontend smoke gates are not hard-coded into completion;
- route or README text is treated as generic structured evidence, not as a special API-smoke category;
- missing frontend assets are not blocked by a one-off HTML rule;
- final answers are assessed and reported instead of blocked by completion gates;
- task-ledger evidence issues are warnings instead of rejected todo updates;
- in-progress task metadata is preserved across `todo_write`.
