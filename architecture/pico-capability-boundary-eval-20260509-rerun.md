# Pico Capability Boundary Evaluation Rerun - 2026-05-09

## Scope

This rerun was executed after the OpenAI-compatible route and DeepSeek route
were restored. The goal was to re-test Pico's current runtime boundary on the
same six-task ladder, especially whether it can now complete a real
frontend/backend student management system.

Evaluation root:

```text
/tmp/pico-capability-eval-20260509-222007
```

Providers exercised:

- OpenAI-compatible via `https://www.right.codes/codex/v1`
  - plain smoke succeeded;
  - XML tool-call smoke succeeded in both Responses and Chat modes;
  - Responses mode completed tasks 1 and 2;
  - some first model requests still timed out on tasks 3 and 5.
- DeepSeek
  - XML tool-call smoke succeeded;
  - completed tasks 3, 5, and 6;
  - generated task 4 artifacts but did not close the run before the external
    deadline.

## Summary

| Task | Capability | Provider | Pico Result | Independent Result |
| --- | --- | --- | --- | --- |
| 1 | Single file + verification | OpenAI Responses | Passed | `python3 app.py` printed `5` |
| 2 | Multi-file CLI + tests | OpenAI Responses | Passed | `4 passed` |
| 3 | Existing-code repair | DeepSeek | Passed | `1 passed` |
| 4 | Static frontend/backend | DeepSeek | Did not close | compile + API smoke passed |
| 5 | Skill behavior | DeepSeek | Passed | `11 passed` |
| 6 | Student management system | DeepSeek | Passed | CRUD smoke passed |

High-level conclusion:

Pico can now complete the "student management system with frontend and backend"
task under DeepSeek in this evaluation. The runtime is no longer stuck at
"partial backend only". The remaining weakness is not code generation quality
for this task. It is control-loop robustness under provider latency, malformed
tool recovery, and verification-stage transition.

## Provider Observations

OpenAI-compatible is usable again, but the transport mode matters:

- Responses mode produced valid tool calls and completed task 1 and task 2.
- Chat fallback previously returned a no-op final on task 1 and timed out on
  task 2. That older failed behavior is still important because Pico's
  completion gate allowed a project-changing request to finish without file
  changes when the model emitted a refusal-like final.
- Responses mode also timed out before any tool call on task 3 and task 5. Pico
  correctly recorded those as `model_error`, but provider first-token latency is
  still a practical failure mode.

DeepSeek was stronger for this rerun:

- It completed repair, skill, and student-system tasks.
- It still struggled on the static full-stack task because the run entered a
  recovery loop around task progression and verification.

## Task Results

### Task 1 - Single File App

Prompt:

```text
Create a Python file app.py that implements add(a, b), prints add(2, 3), and
runs real verification before final answer.
```

Result:

- Pico created `app.py`.
- Pico recorded changed path `app.py`.
- Pico recorded one failed verification first because it tried `python app.py`
  before the file existed.
- Pico recovered, reran `python app.py`, observed output `5`, and completed.

Independent verification:

```text
python3 app.py
5
```

Finding:

The recovery path works here: a failed verification artifact did not poison the
run, and the final gate waited for a later passed verification.

### Task 2 - CLI Todo App With Tests

Prompt:

```text
Build a small JSON-backed Python CLI todo app with todo.py, cli.py, tests, and
run tests before final answer.
```

Result:

- Pico created `todo.py`, `cli.py`, and `tests/test_todo.py`.
- Pico first tried `uv run python -m pytest -q`, which failed because that uv
  environment did not have pytest.
- Pico recovered with `python -m pytest -q`, recorded a passed verification,
  and completed.

Independent verification:

```text
uv run --with pytest python -m pytest -q
4 passed in 0.01s
```

Finding:

This is a meaningful improvement over the earlier run: the same medium
multi-file task now closes instead of stopping after artifact generation.

### Task 3 - Existing-Code Repair

Initial bug:

```python
def divide(a, b):
    return a * b
```

Result:

- OpenAI Responses timed out before any tool call.
- DeepSeek inspected and patched `calculator.py` to use division.
- Pico ran pytest with `uv run --with pytest python -m pytest -q` and completed.

Independent verification:

```text
uv run --with pytest python -m pytest -q
1 passed in 0.00s
```

Finding:

The repair loop is stable when the provider responds: inspect, patch, test,
final.

### Task 4 - Static Frontend/Backend Demo

Prompt:

```text
Build a dependency-free Python http.server backend with GET/POST /api/items,
index.html frontend, README startup instructions, and real verification.
```

Result:

- Pico created `server.py`, `index.html`, and `README.md`.
- Artifact graph detected backend route `/api/items` and frontend reference
  `/api/items`; static API consistency passed.
- Pico did not complete the run. It was still `status=running`,
  `stage=implementing`, with verification task `in_progress` when the external
  deadline killed it.
- Trace shows repeated recovery cost:
  - write rejected by prior-read policy;
  - progress guard blocked stale inspections;
  - malformed `todo_update` calls with empty id;
  - eventually entered verification task but did not run verification before
    timeout.

Independent verification:

```text
uv run python -m compileall .
passed
```

API smoke used the generated `Handler` on a random local port because this
machine already had another process listening on `8080`:

```text
GET /api/items -> 200
POST /api/items {"name":"pear"} -> 201
```

Finding:

This task exposes the current main runtime gap. The artifact was good enough,
but the control loop spent too much budget recovering from tool/progress
mistakes. Pico needs cheaper deterministic recovery at the exact point where an
artifact graph already knows what verification command should run.

### Task 5 - Skill Behavior

Prepared skill:

```text
.pico/skills/strict-pytest/SKILL.md
```

Prompt:

```text
@strict-pytest Build a small Python slugify utility with pytest tests and
follow the active skill exactly.
```

Result:

- OpenAI Responses timed out before any tool call.
- DeepSeek created `slugify.py` and `test_slugify.py`.
- Pico tried two failing pytest commands first, then found `uv run pytest -q`.
- Pico recorded a passed verification and completed.

Independent verification:

```text
uv run pytest -q
11 passed in 0.01s
```

Finding:

The skill loading path works in a real task: the model generated tests and used
pytest as required. The verifier still wastes turns finding the right local
pytest invocation.

### Task 6 - Student Management System

Prompt:

```text
Build a student management system. Requirements: Python backend API,
file-based JSON persistence, fields id/name/age/grade, frontend list/create/
edit/delete flows, README startup instructions, and real verification.
```

Result:

Pico completed the task under DeepSeek.

Generated files:

- `app.py`
- `requirements.txt`
- `static/index.html`
- `README.md`
- `students.json`

Runtime evidence:

- `task_state.status=completed`
- `stage=completed`
- `changed_paths` includes backend, frontend, README, requirements, and data
  file.
- Five tasks were completed: backend, frontend, README, requirements, and
  verification.
- Verification artifact passed with a Flask test-client CRUD smoke:
  - list students;
  - create student;
  - read list again;
  - update student;
  - delete student;
  - confirm empty list.

Independent verification:

```text
uv run --with-requirements requirements.txt python -c "... Flask test client CRUD smoke ..."
200
201 {'age': 18, 'grade': 'A', 'id': 1, 'name': 'Ann'}
200
200
[]
```

Finding:

This is the key result of the rerun: Pico can now independently finish a small
frontend/backend CRUD project with persistence, README, and verification
evidence. It chose Flask, which is acceptable for the prompt because the
requirement was a Python backend, not a specific framework.

## Current Boundary

Pico's current boundary after the rerun:

```text
L1 single-file generation + verification: passed
L2 multi-file CLI + tests: passed
L3 existing-code repair + tests: passed
L4 static frontend/backend artifact generation: artifact passed, run did not close
L5 skill-guided coding + tests: passed
L6 small real CRUD project: passed
```

The important change from earlier evaluations:

Pico is no longer fundamentally unable to do the student-management-system
task. The task completed with real verification. The open problem has shifted
from "cannot build a real project" to "cannot guarantee closure across
providers and intermediate recovery loops".

## Remaining Runtime Gaps

1. No-op final gate gap.

When a project-changing prompt produces no tool calls and no changed paths, the
completion gate should not accept a generic refusal-like final as completed.
This was seen in an earlier OpenAI Chat-mode attempt for task 1.

2. Provider first-request latency.

OpenAI Responses can complete tasks, but it also timed out before any tool call
on tasks 3 and 5. Pico records this cleanly, but no runtime strategy can recover
if the provider never returns. The practical improvement is provider fallback or
resume-with-different-provider support.

3. Verification command discovery is too model-driven.

Several runs first tried a pytest command that failed because pytest was not in
that uv environment, then later recovered. The runtime already has enough local
knowledge to suggest better commands such as:

```text
uv run --with pytest python -m pytest -q
uv run pytest -q
uv run --with-requirements requirements.txt python ...
```

This should be driven more by `VerifierDriver` and less by model guessing.

4. Task progression recovery is too expensive.

Task4 shows the issue clearly: after artifacts existed, the loop still spent
many turns on prior-read recovery, stale-task reminders, and malformed
`todo_update` repair. Runtime reminders need to be actionable enough that the
next valid tool call is obvious and cheap.

5. Artifact graph is useful but underused.

The artifact graph correctly detected route/reference consistency in task 4.
The next step is to let it push the run into a concrete verification action
earlier, instead of merely reporting missing evidence near finalization.

## Recommended Next Changes

1. Add a `project_intent_requires_artifact` completion block.

For prompts that ask to create/build/implement/fix files, a final answer with
no tool calls and no changed paths should become a retry notice or a stopped
report, not `completed`.

2. Add deterministic verifier command candidates.

`VerifierDriver` should emit ranked command candidates from the artifact graph:

- Python files + pytest files: `uv run --with pytest python -m pytest -q`
- Python files without tests: `uv run python -m compileall .`
- Flask app + requirements: import app and use test client when obvious
- stdlib `http.server` handler: instantiate handler on random port for smoke
- frontend/backend route graph: verify API references are covered by backend
  routes before final.

This should stay generic. It should not contain a "student system" special case.

3. Make progress-guard recovery more concrete.

When the runtime blocks an action because task progression is stale, the tool
result should include the exact currently valid task id and a valid example:

```text
Next valid tool: todo_update id="4" status="in_progress"
```

The runtime should not silently perform the update, but it should remove
guesswork.

4. Add provider fallback/resume ergonomics.

If the first model request times out before a tool call, Pico should make it
cheap to retry the same run with a different provider while preserving the
prompt, session, and workspace state.

5. Preserve this evaluation as a regression suite target.

The six tasks now form a useful capability ladder. Future runtime work should
not only run unit tests; it should rerun at least:

- CLI todo app;
- skill slugify task;
- student management system;
- static full-stack task, because that is the one still failing to close.
