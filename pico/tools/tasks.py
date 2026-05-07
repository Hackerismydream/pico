"""Structured task-ledger tools."""

from __future__ import annotations

from ..features import completion
from .spec import ToolPolicy, ToolSpec


def validate_todo_write(agent, args):
    completion.normalize_tasks(args.get("todos"))


def validate_todo_update(agent, args):
    task_id = str(args.get("id", "")).strip()
    if not task_id:
        raise ValueError("id must not be empty")
    status = str(args.get("status", "")).strip()
    if status and status not in completion.TASK_STATUSES:
        raise ValueError(f"invalid task status: {status}")


def tool_todo_write(agent, args):
    tasks = completion.normalize_tasks(args.get("todos"))
    existing_tasks = agent.current_tasks()
    existing_by_id = {task["id"]: task for task in existing_tasks}
    warnings = []
    if existing_tasks:
        next_ids = {task["id"] for task in tasks}
        next_by_id = {task["id"]: task for task in tasks}
        for existing in existing_tasks:
            if existing.get("status") != "completed":
                continue
            proposed = next_by_id.get(existing["id"])
            if proposed is None:
                raise ValueError(f"todo_write cannot remove completed task {existing['id']}; keep it completed in the ledger")
            if proposed.get("status") != "completed":
                raise ValueError(f"todo_write cannot regress completed task {existing['id']} from completed to {proposed.get('status')}")
            if proposed.get("content") != existing.get("content"):
                raise ValueError(f"todo_write cannot rewrite completed task {existing['id']}; keep completed task content stable")
        dropped_open = [
            task["id"]
            for task in existing_tasks
            if task.get("status") in {"pending", "in_progress", "blocked"} and task["id"] not in next_ids
        ]
        if dropped_open:
            warnings.append("replaced open tasks: " + ", ".join(dropped_open))
    changed_count = len(getattr(getattr(agent, "current_task_state", None), "changed_paths", []) or [])
    verifications = list(getattr(getattr(agent, "current_task_state", None), "verifications", []) or [])
    for task in tasks:
        existing = existing_by_id.get(task["id"])
        if existing and existing.get("status") != "completed" and task.get("status") == "completed":
            if completion.is_verification_task(existing):
                latest = verifications[-1] if verifications else None
                if not latest or latest.get("status") != "passed" or not completion.has_structured_verification_evidence(latest):
                    warnings.append(f"{task['id']} verification task completed without passed structured verification evidence")
            if completion.requires_file_change_evidence(existing):
                metadata = dict(existing.get("metadata", {}) or {})
                started_count = int(metadata.get("started_changed_path_count", changed_count) or 0)
                if changed_count <= started_count:
                    warnings.append(f"{task['id']} completed without new file-change evidence")
        if task.get("status") == "in_progress":
            metadata = {}
            if existing and existing.get("status") == "in_progress":
                metadata.update(dict(existing.get("metadata", {}) or {}))
            metadata.update(dict(task.get("metadata", {}) or {}))
            metadata.setdefault("started_changed_path_count", changed_count)
            task["metadata"] = metadata
    agent.set_tasks(tasks)
    message = f"updated {len(tasks)} tasks"
    if len(tasks) >= 3 and not completion.has_verification_task(tasks):
        message += "\nNOTE: task ledger has 3+ tasks but no verification task. Add a verification task before final summary."
    if warnings:
        message += "\n" + "\n".join(f"WARNING: {warning}" for warning in warnings)
    return message


def tool_todo_update(agent, args):
    fields = {}
    for key in ("content", "active_form", "status", "verification"):
        if key in args:
            fields[key] = args[key]
    task_id = str(args.get("id", "")).strip()
    current_tasks = agent.current_tasks()
    current_task = next((task for task in current_tasks if task["id"] == task_id), None)
    if current_task is None:
        raise ValueError(f"task not found: {task_id}")
    requested_status = str(fields.get("status", "")).strip()
    changed_paths = list(getattr(getattr(agent, "current_task_state", None), "changed_paths", []) or [])
    metadata = dict(current_task.get("metadata", {}) or {})
    if requested_status == "in_progress":
        metadata["started_changed_path_count"] = len(changed_paths)
        fields["metadata"] = metadata
    if requested_status == "completed":
        if completion.is_verification_task(current_task):
            verifications = list(getattr(getattr(agent, "current_task_state", None), "verifications", []) or [])
            latest = verifications[-1] if verifications else None
            if not latest or latest.get("status") != "passed" or not completion.has_structured_verification_evidence(latest):
                warning = "verification task completed without passed structured verification evidence"
            else:
                warning = ""
            if warning:
                fields.setdefault("metadata", metadata)["completion_warning"] = warning
        if completion.requires_file_change_evidence(current_task):
            started_count = int(metadata.get("started_changed_path_count", len(changed_paths)) or 0)
            if len(changed_paths) <= started_count:
                warning = "implementation task has no new file-change evidence"
                fields.setdefault("metadata", metadata)["completion_warning"] = warning
    tasks = completion.update_task(current_tasks, task_id, fields)
    agent.set_tasks(tasks)
    task = next(task for task in tasks if task["id"] == task_id)
    message = f"updated {task['id']} {task['status']}"
    warning = (task.get("metadata") or {}).get("completion_warning", "")
    if warning:
        message += f"\nWARNING: {warning}"
    return message


def tool_todo_list(agent, args):
    del args
    return completion.format_tasks(agent.current_tasks())


TOOL_SPECS = [
    ToolSpec(
        name="todo_write",
        schema={"todos": "list[{id:str,content:str,active_form:str,status:str,verification:bool=False}]"},
        description="Create or replace the structured task ledger for the current run.",
        example='<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Implement change","active_form":"Implementing change","status":"in_progress"}]}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="serial"),
        activity=lambda args: "Updating task ledger",
        validate=validate_todo_write,
        run=tool_todo_write,
    ),
    ToolSpec(
        name="todo_update",
        schema={"id": "str", "status": "str", "content": "str?", "active_form": "str?", "verification": "bool?"},
        description="Update one task in the current task ledger.",
        example='<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="serial"),
        activity=lambda args: f"Updating task {str(args.get('id', '')).strip()}" if str(args.get("id", "")).strip() else "Updating task",
        validate=validate_todo_update,
        run=tool_todo_update,
    ),
    ToolSpec(
        name="todo_list",
        schema={},
        description="Show the current task ledger.",
        example='<tool>{"name":"todo_list","args":{}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="parallel"),
        activity=lambda args: "Reading task ledger",
        run=tool_todo_list,
    ),
]

