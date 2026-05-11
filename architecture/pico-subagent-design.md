# Pico Subagent Runtime Design

## Goal

Pico adds subagents as a bounded runtime capability, not as an uncontrolled
second agent loop. The main `Pico.ask()` remains the coordinator. Subagents
perform scoped exploration or implementation work, then report back through
structured notifications. The coordinator still owns synthesis, verification
decisions, and the final answer.

This follows the useful shape of `cc-mini` coordinator mode:

- `Agent` launches workers.
- `SendMessage` continues a previous worker.
- `TaskStop` stops a running worker.
- Worker results return as structured notifications.

Pico keeps the design integrated with its own control plane: task state, trace,
report, TUI status, tool policy, and completion gate.

## Runtime Shape

```text
User request
  |
  v
Pico.ask() coordinator
  |
  +-- agent / send_message / task_stop tools
  |        |
  |        v
  |   SubagentManager
  |      |        |
  |      v        v
  |   Explore   Worker
  |   read-only scoped write
  |      \        /
  |       v      v
  |   subagent notification
  |        |
  |        v
  +-- Runtime Event Bus
       |
       +-- task_state.subagents
       +-- trace.jsonl / report.json
       +-- TUI /agents and status bar
       +-- coordinator history message
```

## Subagent Types

### Explore

`Explore` is a read-only codebase investigator.

Allowed tools:

- `list_files`
- `read_file`
- `search`
- `run_shell`
- `todo_list`

Runtime settings:

- `read_only=True`
- `approval_policy=never`
- no file-writing tools exposed
- no nested subagent tools exposed

Use it for open-ended code search, architecture questions, and independent
inspection where the exact file is not known.

### Worker

`Worker` is a scoped implementation agent.

Allowed tools:

- read/search tools
- `write_file`
- `write_files`
- `patch_file`
- todo tools

Runtime settings:

- requires explicit `write_scope`
- writes outside `write_scope` are rejected before execution
- no shell tool; verification remains owned by the coordinator runtime
- no nested subagent tools exposed
- still uses Pico's regular completion and verification gates

Use it only when the coordinator can name the files or directories it owns. The
first implementation does not allow unbounded write-heavy workers.

## Public Tools

### `agent`

Launches a subagent.

Important args:

- `description`
- `prompt`
- `subagent_type`: `Explore` or `Worker`
- `background`: defaults to true
- `write_scope`: required for `Worker`
- `max_steps`: optional child run step cap

### `send_message`

Continues an existing completed or idle subagent by task id. This keeps the
subagent's own context instead of spawning a fresh child run.

### `task_stop`

Requests cancellation for a running subagent. Stopped subagents report back with
status `killed` once their child run observes the cancellation event.

## Notification Contract

Subagents report through structured notifications:

```text
<subagent-notification>
<task-id>agent-1234abcd</task-id>
<status>completed|failed|killed</status>
<description>Inspect runtime</description>
<result>...</result>
<usage>
  <tool_uses>2</tool_uses>
  <duration_ms>1200</duration_ms>
</usage>
</subagent-notification>
```

The JSON form is persisted in:

- `TaskState.subagents`
- `report.json.subagents`
- session `subagents`
- trace events such as `subagent_started` and `subagent_completed`

The XML-like rendering is inserted into coordinator history so the model can
consume worker results on the next turn.

## Safety Rules

Pico's subagent design has four hard boundaries:

1. The coordinator owns understanding.

   The main agent must read notifications and synthesize the next step. Worker
   results are evidence, not final truth.

2. Explore is read-only.

   It cannot use write tools. If it tries, the child runtime returns a tool
   rejection and the notification includes that tool error.

3. Worker writes are scoped.

   `write_scope` is mandatory for `Worker`. `write_file`, `write_files`, and
   `patch_file` reject paths outside that scope. Worker does not expose
   `run_shell`, because shell commands cannot be scoped reliably by file path.

4. Subagents do not bypass completion.

   A worker completing does not make the parent task complete. The parent
   `CompletionGate` still checks tasks, changed paths, and verification
   evidence before final.

## Why This Is Not Just Delegate

The old `delegate` tool was a synchronous read-only child call:

```text
parent -> child.ask(task) -> plain text result
```

The new subagent path has lifecycle and observability:

```text
spawn -> running status -> notification -> trace/report/TUI -> coordinator synthesis
```

That difference matters in interviews. The feature is not "recursion"; it is a
small coordinator control surface with typed workers, scoped permissions, and
auditable results.

## Current Limits

- No git worktree isolation yet.
- No automatic merge planner.
- No multi-worker conflict resolution beyond `write_scope`.
- Background subagents run in local daemon threads.
- Provider failures are reported as subagent failures; the coordinator decides
  whether to retry or continue.

These limits are intentional. Pico first makes the single-machine, observable
subagent loop reliable before adding heavier isolation.
