# Pico Capability Boundary Evaluation - 2026-05-09

## Scope

This evaluation ran Pico against a six-task capability ladder. The goal was not
to prove one demo works. The goal was to identify where Pico's current runtime
starts losing control: planning, tool use, context, verification, repair, final
gating, or provider transport.

Evaluation root:

```text
/tmp/pico-capability-eval-20260509-215242
```

Provider results:

- `openai` through `https://www.right.codes/codex/v1` failed before evaluation:
  `HTTP 403`, first as quota exhausted, then after replacing the test key as
  channel permission denied.
- `anthropic` failed before evaluation with `HTTP 403`.
- `deepseek` completed tasks 1 and 3, partially generated tasks 2 and 4, then
  later failed with `HTTP 402 Insufficient Balance`.
- Local Ollama was not available on `127.0.0.1:11434`.

This means the evaluation is useful for the lower levels and partial mid-level
behavior, but tasks 5 and 6 were blocked by provider availability rather than by
Pico runtime behavior.

## Summary

| Task | Capability | Result | Main Evidence |
| --- | --- | --- | --- |
| 1 | Single file + verification | Passed | `app.py`, `python app.py` output `5`, completed run |
| 2 | Multi-file CLI + tests | Artifact passed, agent loop failed | Generated `todo.py`, `cli.py`, `tests/test_todo.py`; manual pytest: `9 passed`; Pico timed out before final |
| 3 | Repair existing code + regression test | Passed | Fixed `calculator.py`; Pico ran pytest and completed |
| 4 | Static frontend/backend integration | Partial, provider failed | Generated `server.py`, `index.html`; API consistency passed; missing README and verification when DeepSeek returned 402 |
| 5 | Skill behavior | Not run | Provider unavailable before task |
| 6 | Real student management system | Not run | Provider unavailable before task |

## Task 1 - Single File App

Prompt:

```text
Create a Python file app.py that implements a function add(a, b) and a small
main block that prints add(2, 3). Run real verification before final answer.
```

Result:

- DeepSeek run completed.
- Generated `app.py`.
- Pico recorded one task, changed path `app.py`, and a passed verification.
- Verification artifact command: `python app.py`.
- Output observed: `5`.
- Completion gate status: `completed`.

Boundary finding:

Pico can complete a simple single-file task with a real verification artifact.
The runtime state is coherent at this level.

## Task 2 - CLI Todo App With Tests

Prompt:

```text
Build a small Python CLI todo app. Requirements:
- todo.py exposes add_task, list_tasks, complete_task
- cli.py provides command line usage
- tests/test_todo.py covers add/list/complete
- Use JSON file persistence.
- Run tests before final answer.
```

Result:

- Pico generated:
  - `todo.py`
  - `cli.py`
  - `tests/test_todo.py`
- Pico created a four-item task ledger.
- The run hit the 5 minute external deadline before final answer.
- `task_state.json` stayed `status=running`, `stage=implementing`.
- Open tasks remained:
  - `tests` task `in_progress`
  - `verification` task `pending`
- No `VerificationArtifact` was recorded by Pico.

Independent verification:

```text
uv run --with pytest python -m pytest -q
9 passed in 0.01s
```

Boundary finding:

The generated artifact quality was good enough, but the agent loop did not
close the task. Pico still has a progress-control gap for medium multi-file
tasks: it can produce files but may spend too many turns inspecting or
recovering from malformed calls instead of marking the current task complete and
running verification.

This is not a template problem. It is a next-action pressure problem:

```text
files are done -> tests task should close -> verification should run -> final
```

The runtime had enough evidence to push harder, but it did not force that
transition before the external deadline.

## Task 3 - Repair Existing Code

Initial files:

```text
calculator.py
tests/test_calculator.py
```

The bug was `divide(a, b)` returning `a * b`.

Prompt:

```text
The existing tests are failing. Inspect the project, fix the bug with the
smallest reasonable change, and run the tests before final answer.
```

Result:

- Pico inspected the project.
- Pico patched `calculator.py` from multiplication to division.
- Pico ran pytest.
- Completion gate status: `completed`.

Verification artifact:

```text
python -m pytest tests/test_calculator.py -v 2>&1
1 passed
```

Observed issue:

The run also recorded an earlier bad verification command:

```text
cd /home/user/workspace && python -m pytest tests/test_calculator.py -v 2>&1 || true
```

Because the command used `|| true`, the shell exit code was `0` even though the
`cd` failed. Pico later recovered and ran the correct command, but this exposes
a verifier-quality bug: `verification_from_shell()` trusts exit code too much
and does not reject commands that mask failure with `|| true`.

Boundary finding:

Pico is already useful for small existing-code repair. It can read, patch, test,
and finish. The next improvement should harden verification evidence quality,
especially shell commands that hide failure.

## Task 4 - Static Frontend/Backend Integration

Prompt:

```text
Build a tiny full-stack demo without external dependencies.
Backend: Python stdlib http.server app in server.py with routes:
- GET /api/items
- POST /api/items
Frontend: index.html with native JS that calls the backend routes.
Include README startup instructions.
Run real verification before final answer.
```

Result:

- Pico generated:
  - `server.py`
  - `index.html`
- Pico did not generate `README.md`.
- Pico did not run verification before provider failure.
- DeepSeek returned `HTTP 402 Insufficient Balance`.

Artifact graph evidence:

```text
backend_routes: ["/api/items", "/", "/index.html"]
frontend_references: ["/api/items"]
api_consistency: passed
suggested verification: uv run python -m compileall .
```

Independent verification:

```text
uv run python -m compileall .
passed
```

Boundary finding:

The artifact graph is doing useful work: it recognized backend/frontend and
proved the frontend API reference was covered by backend routes. The failure was
not API consistency. The task stopped before docs and verification due provider
failure, but trace also shows repeated `todo_update` invalid-argument calls and
read/list detours. That is another next-action pressure issue.

## Task 5 - Skill Behavior

Prepared skill:

```text
.pico/skills/strict-pytest/SKILL.md
```

Intended prompt:

```text
@strict-pytest Build a small slugify utility with tests. Follow the active skill exactly.
```

Result:

Not run. Remote providers were unavailable before this task.

Boundary finding:

No runtime conclusion from this live evaluation. The existing unit coverage
still verifies skill discovery and prompt metadata, but live skill-to-behavior
compliance remains unevaluated.

## Task 6 - Student Management System

Result:

Not run. Remote providers were unavailable before this task.

Boundary finding:

No new conclusion from this run. Earlier student-system runs already showed
that Pico can create partial backend/frontend artifacts but struggles to close
README and verification under provider latency and long task pressure.

## Capability Boundary

Current boundary based on this run:

```text
L1 single-file generation + verification: passed
L2 multi-file generation: artifact passed, loop did not close
L3 existing-code repair + tests: passed
L4 frontend/backend artifact graph: partial but promising
L5 skill behavior: blocked by provider
L6 real project completion: blocked in this run; still known weak area
```

The strongest implemented pieces are:

- tool execution and file writing;
- task ledger persistence;
- trace/session/report evidence;
- artifact graph extraction;
- static API consistency checks;
- completion gate after verification evidence exists.

The weak pieces are:

- medium-task next-action pressure after files are already generated;
- invalid `todo_update` recovery cost;
- automatic transition from generated tests to verification;
- verification evidence quality when shell commands mask failures;
- provider budget/latency resilience.

## Recommended Next Runtime Fixes

1. Harden verification evidence.

Reject or mark suspicious verification commands when they contain failure masks:

```text
|| true
; true
exit 0
```

These commands should not produce `status=passed` unless the verifier can prove
the underlying test command passed.

2. Add artifact-to-task completion pressure.

When the active task is about creating tests and the expected test file already
exists, the planner should push `todo_update` or verification instead of
allowing more read/list detours.

3. Add verification-priority pressure near budget end.

When `remaining_tool_steps <= 3` and `verification_plan.missing_evidence` exists,
the planner should prefer the safe verifier action or force a truthful stopped
report. This would have improved Task 2.

4. Reduce invalid `todo_update` recovery cost.

If the model calls `todo_update` with empty args while exactly one active task
exists, runtime can return a targeted correction including the active task id
and the likely next valid update. It should not silently infer the update, but
it can make recovery cheaper.

5. Keep provider failures separate in reports.

The evaluation proved this matters: provider errors dominated tasks 4-6. Reports
should make provider transport failure a first-class category so it does not get
mixed with runtime completion failure.

