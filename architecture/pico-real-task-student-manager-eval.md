# Pico Real Task Evaluation: Student Management System

Date: 2026-05-08

## Goal

Use Pico through the TUI path to build a real full-stack student management system:

- FastAPI backend with SQLite persistence and CRUD APIs.
- React + Vite + TypeScript frontend with list/create/edit/delete/search.
- README startup instructions.
- Minimal tests or verification.

The purpose was not only to see whether the model can generate code, but to find the runtime gaps that stop Pico from completing a realistic project.

## Test Setup

Scratch workspace:

```bash
/tmp/pico-e2e-student-manager
```

Main commands used during the evaluation:

```bash
uv run pico --cwd /tmp/pico-e2e-student-manager \
  --env-file /Users/martinlos/code/pico/.env \
  --provider deepseek \
  --approval auto \
  --max-steps 40 \
  --max-new-tokens 12000
```

The initial interaction was driven through cmux with Computer Use. Shell commands were used afterwards to inspect trace files and verify generated artifacts.

## What Failed First

### 1. Chinese input through Computer Use was corrupted

The TUI accepted the submitted text, but the trace showed the Chinese parts were dropped. The recorded request became mostly punctuation plus English technical words.

Evidence:

```text
user_request: "： FastAPI  CRUD API， id、name、age、grade、email； SQLite ； React + Vite + TypeScript，、、、、； README ；；，。"
```

Conclusion: this is an input-path reliability issue for automated UI testing. For the fair project-generation run, the same task was resubmitted in ASCII English.

### 2. Provider configuration was not portable across target workspaces

Launching Pico in an empty target repo depended on shell-level environment setup. This failed in cmux and produced:

```text
OpenAI-compatible request failed with HTTP 401: missing API Key
```

Fix implemented:

- Added `--env-file` so Pico can load provider credentials from an explicit config file while operating inside another project workspace.

### 3. OpenAI/right.codes route was not usable for this run

The OpenAI-compatible `/responses` route either hung or returned gateway errors. The chat fallback returned:

```text
auth_unavailable: no auth available (providers=codex, model=gpt-5.4)
```

DeepSeek-compatible Anthropic route worked for a small sanity prompt, so the real task run used:

```bash
--provider deepseek
```

Fix implemented:

- Added `--openai-api-mode auto|responses|chat`.
- `auto` can route known chat-only compatible gateways away from `/responses`.

## What Failed During Project Generation

### 4. Single-file tool protocol was too weak for a full project

The original tool set had `write_file`, but a realistic app needs many files. The model tried to put multi-file content into a JSON tool call, which broke because large multi-line strings are easy to truncate or malform.

Fix implemented:

- Added `write_files`.
- Added XML multi-file syntax:

```xml
<tool name="write_files">
  <file path="README.md"><content>...</content></file>
  <file path="backend/main.py"><content>...</content></file>
</tool>
```

Result: Pico created 13-14 files in one tool call instead of spending dozens of steps writing one file at a time.

### 5. Output budget truncation caused malformed tool calls

With `--max-new-tokens 4096`, the model started producing the correct `write_files` call, but the provider stopped at `max_tokens`, leaving an incomplete `<tool>` block.

Evidence from raw provider response:

```json
"stop_reason": "max_tokens"
```

Mitigation used:

```bash
--max-new-tokens 12000
```

Remaining design issue: the runtime should detect max-token truncation from provider metadata and ask the model to split the scaffold into smaller batches.

### 6. After writing files, Pico entered a read-only inspection loop

After scaffold generation, the model repeatedly called `list_files` and `read_file` instead of running verification or producing a final answer.

Fix implemented:

- Added a read-only stall guard.
- After repeated read-only tools, further read-only calls are rejected with:

```text
read-only inspection budget exhausted; run a verification command, modify files, or return a final answer
```

Observed effect:

- The model switched to `run_shell` after the guard fired.
- This is an improvement, but not a full completion guarantee.

## Generated Project Result

Pico generated these project files:

```text
README.md
backend/database.py
backend/main.py
backend/models.py
backend/requirements.txt
backend/tests/test_api.py
frontend/index.html
frontend/package.json
frontend/src/App.tsx
frontend/src/api.ts
frontend/src/main.tsx
frontend/tsconfig.json
frontend/vite.config.ts
```

Manual verification results:

```bash
cd /tmp/pico-e2e-student-manager/backend
source venv/bin/activate
python -m pytest -q
```

Result:

```text
4 passed, 8 warnings
```

```bash
cd /tmp/pico-e2e-student-manager/frontend
npm install
npm run build
```

Result:

```text
✓ built in 241ms
```

## Remaining Product Gap

Pico still did not complete the task end-to-end by itself. The last run stopped with:

```text
Stopped after reaching the step limit without a final answer.
```

There is also a generated full-stack integration bug:

- Frontend uses `BASE = "/api"`.
- Vite proxy maps `"/api"` to `http://localhost:8000` without rewrite.
- Backend exposes `/students`, not `/api/students`.

So backend tests and frontend build pass, but the browser workflow would call the wrong backend path.

This is the important interview-level finding: build/test passing is not the same as task completion for full-stack work. The harness needs an app-level smoke check.

## Pico Changes Made From This Evaluation

Implemented runtime improvements:

- Explicit provider config loading with `--env-file`.
- OpenAI-compatible API mode selection with `--openai-api-mode`.
- Batch file creation tool `write_files`.
- XML multi-file parsing for large scaffolds.
- Read-only stall guard to break inspection loops.
- Prompt rule to verify frontend API paths/proxy rules against backend routes.

## Next Iteration

The next high-value runtime improvements are:

1. Add provider truncation awareness.
   If the provider reports `stop_reason=max_tokens`, Pico should not treat the output as generic malformed XML. It should ask for a smaller `write_files` batch.

2. Add forced finalization near step limit.
   When tool budget is nearly exhausted, Pico should stop accepting exploratory tools and require either a verification command or a final answer.

3. Add full-stack smoke verification guidance.
   For frontend/backend apps, Pico should run or synthesize a route-level check: frontend API base + proxy rewrite + backend route table.

4. Add run report quality gates.
   A run should distinguish:
   - files generated,
   - tests passed,
   - app-level smoke passed,
   - final answer produced.

Current conclusion:

Pico can now generate a non-trivial full-stack project and pass backend/frontend build checks, but it still needs stronger completion governance before I would claim it can reliably finish this class of task unattended.
