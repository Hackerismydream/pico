# Pico Student Manager Real Task Report v3

## Task

Prompt:

> Build a student management system in this workspace. Requirements: backend API plus frontend UI. Use Python FastAPI for backend, file-based JSON persistence, student fields id name age grade. Frontend should be native HTML CSS JS with list create edit delete. Include README startup instructions. Run real verification before final answer: backend route smoke and frontend/backend API path consistency.

## Environment

- Workspace under `/tmp/pico-student-manager-real-20260509-*`
- Main usable provider: `deepseek`
- OpenAI-compatible `gpt-5.4` and Anthropic-compatible `claude-sonnet-4-6` both failed with HTTP 403 from the configured gateway during this run.
- Computer Use was used against `cmux`; direct long command entry into the terminal UI was unreliable because the command was corrupted by terminal escape text. The actual controlled evaluation was therefore run through shell commands while keeping the UI observation as a test note.

## Iterations

### v9

Outcome: partial project only.

Observed:

- Pico created a task ledger.
- It wrote `main.py`, `requirements.txt`, `index.html`, and `README.md`.
- The frontend file contained a literal `<![CDATA[` wrapper.
- After a `write_file` rejection for missing prior read, the model repeatedly retried the same invalid write.

Root causes:

- XML parser did not strip CDATA wrappers.
- Tool rejection feedback was too weak; the runtime did not provide an explicit recovery action.
- Artifact graph did not extract frontend API paths from absolute URLs or template strings.

Fixes:

- Strip CDATA in XML tool content.
- Add explicit prior-read recovery messages and runtime reminder trace events.
- Extract API paths from absolute URLs and template strings.

### v10/v11

Outcome: project advanced further but stopped at step limit.

Observed:

- Pico recovered from prior-read rejection by reading the file.
- `write_files` could still overwrite existing files without prior read.
- The model rewrote task ledgers and regressed completed work.
- It repeatedly read files after an active task already had file-change evidence.

Root causes:

- `write_files` had weaker safety semantics than `write_file`.
- Completed task ledger items could be regressed by a later `todo_write`.
- Runtime reminders were soft only; ignored reminders did not change tool execution.
- Current runtime state was only implicit in history, not a first-class prompt section.

Fixes:

- Require prior read for existing files in `write_files`.
- Reject `todo_write` that removes, rewrites, or regresses completed tasks.
- Add `Runtime state` into every prompt: stage, tasks, changed paths, artifact summary, API paths, verifier suggestions, active-task pressure.
- Escalate repeated stale read-only inspection into `progress_guard_stale_task`.
- Assess completion quality before writing a step-limit report.

### v13

Outcome: functionally close, still stopped at step limit.

Observed:

- Pico completed backend, frontend, README, and ran a real backend smoke test.
- Smoke evidence passed: empty list, POST, GET after create, DELETE, final GET.
- Verification task remained `in_progress`, so final status was `incomplete`.

Root cause:

- `VerificationArtifact` and `TaskLedger` were not synchronized. A passed verification artifact did not close the open verification task.

Fix:

- Passed verification artifacts now auto-complete the open verification task and record metadata linking the task to the verification command.

### v14

Outcome: still stopped at step limit.

Observed:

- Pico again created backend, frontend, README, and entered verification.
- It repeatedly hallucinated absolute workspace paths and tried `pip`/bare `python` flows.
- It did not reliably use the correct `uv run --with-requirements requirements.txt ...` command even after project files existed.

Root causes remaining:

- Shell environment guidance is still too weak for dependency-aware verification.
- Verifier suggestions only offered `uv run python -m compileall .`, which does not install or expose FastAPI dependencies.
- The model can spend too many steps debugging the environment instead of using a deterministic suggested verifier.

Fixes added after v14:

- Prompt now states that `run_shell` already runs in workspace root and should not `cd` into guessed paths.
- Prompt now tells the model to prefer `uv run --with-requirements requirements.txt ...` when a Python project has `requirements.txt`.
- Verifier suggestions now use `uv run --with-requirements requirements.txt` for Python projects with `requirements.txt`.

## Current Assessment

Pico is substantially better than the starting point, but the v14 real-task run still did not fully complete independently.

What improved:

- It can create the multi-file project.
- It can recover from prior-read rejection.
- It no longer writes CDATA wrappers into files.
- It no longer regresses completed tasks.
- It has artifact graph evidence for backend/frontend/docs/dependencies.
- It records verification evidence and can auto-close verification tasks when verification passes.
- It reports incomplete state accurately instead of claiming success.

What remains:

- Verification command selection is still too model-dependent.
- The runtime should probably promote verifier suggestions into stronger next-action guidance when a verification task is active.
- A deterministic verifier driver may be needed for common project shapes, not as a student-system template, but as a generic "project metadata -> verification command" executor with model-visible evidence.

## Verification

Commands run after the code changes:

```bash
uv run python -m pytest tests/test_runtime_consumers.py tests/test_completion_controller.py tests/test_pico.py -q
uv run ruff check .
git diff --check
uv run python -m pytest -q
```

Observed:

- Targeted suite: `109 passed`
- Ruff: `All checks passed`
- Diff check: passed
- Full suite: `184 passed, 6 warnings`
