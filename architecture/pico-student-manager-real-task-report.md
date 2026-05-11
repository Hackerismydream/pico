# Pico Real Task Evaluation: Student Management System

Date: 2026-05-08 23:15 CST

## Task

Prompt Pico to build a complete full-stack Student Management System in an empty workspace:

- Backend CRUD APIs for students: id, name, age, email, major, enrollment_date.
- Local persistence using SQLite or JSON.
- Frontend UI for list, add, edit, delete, search/filter.
- README run instructions.
- Backend/API verification and frontend/build verification.
- Frontend API paths/proxy must match backend routes.

## Method

I ran Pico through a real one-shot CLI task and observed it with Computer Use via cmux where possible. macOS blocks Computer Use access to Terminal, and cmux mangled long command input, so the actual reproducible runs were launched with local exec while cmux was used as visual evidence that the TUI/runtime was active.

Primary run artifacts:

- DeepSeek hanging run: `/tmp/pico-student-manager-real-ds-tsqUbN`
- DeepSeek partial FastAPI run: `/tmp/pico-student-manager-real-v3-97D3TB`
- DeepSeek timeout/report run: `/tmp/pico-student-manager-real-v4-hah0nE`
- DeepSeek provider-error/report run: `/tmp/pico-student-manager-real-v5-Va0nA5`
- OpenAI partial Express run: `/tmp/pico-student-manager-real-openai-jtzTDJ`

## Result

Pico still cannot reliably complete this full-stack project end to end.

It did improve from "hang with no report" to "fail with trace/report", and it can now make partial project progress. However, the final acceptance criteria were not met in any run.

Best observed progress:

- DeepSeek run created partial FastAPI backend files:
  - `backend/requirements.txt`
  - `backend/database.py`
  - `backend/models.py`
  - `backend/main.py`
- OpenAI run created a more complete Node/Express project with `package.json`, `server/index.js`, and `vite.config.js`, but this violated the user-requested FastAPI backend stack.

No run completed frontend + backend + README + verification with all task ledger items closed.

## Issues Found

1. Provider calls could hang the whole run.

   Earlier runs stayed at `model_requested` with no final report. This made the session impossible to evaluate cleanly.

2. Provider errors were not normalized enough.

   DeepSeek sometimes returned a response shape where Pico could not extract text. The run now records this as `model_error`, but completion still depends heavily on provider stability.

3. The model sometimes emits malformed tool calls.

   One real run called `todo_write` with empty args. Pico rejected it with an example, and the model recovered on the next turn.

4. The model can violate explicit stack requirements.

   The OpenAI run ignored the requested FastAPI backend and built Express instead. This is a task-spec adherence failure, not just a code-quality issue.

5. The model can enter read-only loops after writing code.

   The DeepSeek FastAPI run repeatedly read `backend/main.py`, `backend/models.py`, and `backend/database.py` after writing them, without progressing to frontend, README, or verification.

6. Task ledger status did not reliably advance.

   The model created a useful todo list, but left early tasks `in_progress` or `pending` even after writing files. The useful signal is the incomplete ledger itself; Pico should assess and report that state instead of relying on a hard final gate to repair it.

## Iterations Implemented

1. Runtime model-error closure.

   `Pico.ask()` now catches model/provider exceptions, marks the run as `model_error`, records a `model_error` trace event, writes `task_state.json`, and writes `report.json`.

2. Provider timeout normalization.

   Provider clients now normalize `TimeoutError` and `socket.timeout` into clearer runtime errors that include the configured timeout.

3. Runtime hard deadline.

   Model calls now run through a daemon worker thread with a join timeout, so the main runtime can recover even if the provider call does not return.

4. Small-batch project prompting.

   The runtime prefix now tells the model to keep `write_files` small, preserve explicit requested stacks, include verification tasks, and avoid rereading files it just wrote unless verification failed.

5. Read-only loop guard.

   Read-heavy loops and repeated reads of files changed in the current run are now better treated as runtime warnings. The remaining hard blocks should stay limited to safety and protocol failures such as repeated identical tool calls, invalid arguments, unsafe paths, or prior-read violations.

## Current Judgment

Pico is now better at producing evidence when it cannot finish, but not yet good enough to claim it can independently finish a full-stack project.

The next necessary upgrades are:

- Add task-spec adherence assessment that extracts required stack terms from the user request and flags conflicting writes, such as Express when FastAPI was requested.
- Add deterministic progress reminders tied to TaskLedger status: after writing backend files, pressure the model toward `todo_update` or next task work before more reads.
- Add a project skeleton planner that turns a full-stack request into bounded file batches before implementation.
- Add a verification planner that knows expected commands per stack and records missing verification as first-class debt.
- Add retry/provider fallback policy: if one provider returns empty text or times out, continue with another configured provider instead of stopping the run.
