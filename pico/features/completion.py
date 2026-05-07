"""Task completion control helpers for the Pico runtime."""

from __future__ import annotations

import re
from copy import deepcopy

from ..core.workspace import now

TASK_STATUSES = {"pending", "in_progress", "completed", "blocked"}
COMPLEX_REQUEST_PATTERN = re.compile(
    r"(?i)(\bfrontend\b|\bbackend\b|\bfront[- ]?end\b|\bback[- ]?end\b|\bfull[- ]?stack\b|\btests?\b|\bverify\b|\bverification\b|\bbuild\b|\bcrud\b|\bapi\b|\bui\b|前后端|接口|页面|数据存储|验收|测试|验证)"
)
WORKSPACE_PROGRESS_PATTERN = re.compile(
    r"(?i)\b(create|build|implement|add|write|update|fix|scaffold|generate|set up)\b|做一个|实现|创建|新增|编写|修改|修复|搭建"
)
QUESTION_PATTERN = re.compile(r"(?i)^\s*(explain|what|why|how|tell me|介绍|解释|什么|为什么|怎么)\b")
WORKSPACE_INSPECTION_PATTERN = re.compile(
    r"(?i)\b(inspect|list|show|scan|look at|check)\b.*\b(repo|repository|workspace|files?|tree|structure|directory)\b"
    r"|看下|看一下|看看|当前仓库|仓库.*(有啥|有什么|结构|文件)|文件结构|目录结构|列.*文件"
)
VERIFICATION_COMMAND_PATTERN = re.compile(
    r"(?i)\b(pytest|unittest|ruff|mypy|pyright|tsc|npm\s+(run\s+)?(test|build|lint)|pnpm\s+(test|build|lint)|yarn\s+(test|build|lint)|uv\s+run|curl|playwright|vitest|python\d*)\b"
)
EXIT_CODE_PATTERN = re.compile(r"exit_code:\s*(-?\d+)")
STDOUT_PATTERN = re.compile(r"stdout:\n(?P<stdout>.*?)(?:\nstderr:\n|$)", re.S)
STDERR_PATTERN = re.compile(r"stderr:\n(?P<stderr>.*)$", re.S)


def is_complex_request(text: str) -> bool:
    return bool(COMPLEX_REQUEST_PATTERN.search(str(text or "")))


def requires_verification(text: str) -> bool:
    return is_complex_request(text) or bool(re.search(r"(?i)\b(test|tests|verify|verification|build|lint)\b|测试|验证", str(text or "")))


def expects_workspace_progress(text: str) -> bool:
    text = str(text or "")
    if QUESTION_PATTERN.search(text):
        return False
    return bool(WORKSPACE_PROGRESS_PATTERN.search(text))


def expects_workspace_inspection(text: str) -> bool:
    return bool(WORKSPACE_INSPECTION_PATTERN.search(str(text or "")))


def expects_task_ledger(text: str) -> bool:
    return is_complex_request(text) and expects_workspace_progress(text)


def normalize_task(item: dict, fallback_id: str) -> dict:
    task_id = str(item.get("id") or fallback_id).strip() or fallback_id
    content = str(item.get("content") or item.get("subject") or "").strip()
    active_form = str(item.get("active_form") or item.get("activeForm") or content).strip()
    status = str(item.get("status") or "pending").strip()
    if status not in TASK_STATUSES:
        raise ValueError(f"invalid task status: {status}")
    if not content:
        raise ValueError(f"task {task_id} missing content")
    if not active_form:
        active_form = content
    created_at = str(item.get("created_at") or now())
    return {
        "id": task_id,
        "content": content,
        "active_form": active_form,
        "status": status,
        "verification": bool(item.get("verification", False)),
        "metadata": dict(item.get("metadata", {}) or {}),
        "created_at": created_at,
        "updated_at": now(),
    }


def normalize_tasks(items) -> list[dict]:
    if not isinstance(items, list):
        raise ValueError("todos must be a list")
    tasks = [normalize_task(item, f"task_{index}") for index, item in enumerate(items, start=1)]
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task ids must be unique")
    if sum(1 for task in tasks if task["status"] == "in_progress") > 1:
        raise ValueError("only one task can be in_progress")
    return tasks


def update_task(tasks: list[dict], task_id: str, fields: dict) -> list[dict]:
    task_id = str(task_id or "").strip()
    if not task_id:
        raise ValueError("id must not be empty")
    found = False
    updated = []
    for task in tasks:
        next_task = dict(task)
        if task["id"] == task_id:
            found = True
            merged = {**next_task, **fields, "id": task_id}
            next_task = normalize_task(merged, task_id)
            next_task["created_at"] = task.get("created_at", next_task["created_at"])
        updated.append(next_task)
    if not found:
        raise ValueError(f"task not found: {task_id}")
    if sum(1 for task in updated if task["status"] == "in_progress") > 1:
        raise ValueError("only one task can be in_progress")
    return updated


def task_counts(tasks: list[dict]) -> dict:
    total = len(tasks)
    completed = sum(1 for task in tasks if task.get("status") == "completed")
    open_count = sum(1 for task in tasks if task.get("status") in {"pending", "in_progress", "blocked"})
    return {"total": total, "completed": completed, "open": open_count}


def has_verification_task(tasks: list[dict]) -> bool:
    return any(task.get("verification") or re.search(r"(?i)verif|test|build|lint|验证|测试", task.get("content", "")) for task in tasks)


def is_verification_task(task: dict) -> bool:
    return bool(task.get("verification")) or bool(re.search(r"(?i)verif|test|lint|typecheck|验收|验证|测试", task.get("content", "")))


def requires_file_change_evidence(task: dict) -> bool:
    if is_verification_task(task):
        return False
    text = f"{task.get('content', '')} {task.get('active_form', '')}"
    return bool(re.search(r"(?i)\b(implement|build|create|add|write|update|fix|scaffold)\b|实现|创建|新增|编写|修改|修复", text))


def format_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "Task ledger: empty"
    lines = ["Task ledger:"]
    for task in tasks:
        marker = " verification" if task.get("verification") else ""
        lines.append(f"- {task['id']} [{task['status']}]{marker} {task['content']}")
    return "\n".join(lines)


def is_verification_command(command: str) -> bool:
    return bool(VERIFICATION_COMMAND_PATTERN.search(str(command or "")))


def verification_from_shell(command: str, result: str) -> dict | None:
    if not is_verification_command(command):
        return None
    match = EXIT_CODE_PATTERN.search(str(result or ""))
    exit_code = int(match.group(1)) if match else 0
    status = "passed" if exit_code == 0 else "failed"
    summary_lines = [line for line in str(result or "").splitlines() if line.strip()]
    summary = summary_lines[-1] if summary_lines else status
    stdout_match = STDOUT_PATTERN.search(str(result or ""))
    stderr_match = STDERR_PATTERN.search(str(result or ""))
    stdout = stdout_match.group("stdout").strip() if stdout_match else ""
    stderr = stderr_match.group("stderr").strip() if stderr_match else ""
    output_observed = "\n".join(part for part in (stdout, stderr) if part and part != "(empty)")
    if not output_observed:
        output_observed = summary
    return {
        "command": str(command),
        "exit_code": exit_code,
        "status": status,
        "summary": summary[:500],
        "checks": [
            {
                "command": str(command),
                "expected": "command exits with code 0",
                "output_observed": output_observed[:1200],
                "result": "PASS" if status == "passed" else "FAIL",
                "adversarial_probe": False,
            }
        ],
        "created_at": now(),
    }


def latest_verification_status(verifications: list[dict]) -> str:
    if not verifications:
        return "not_run"
    return str(verifications[-1].get("status", "not_run"))


def has_structured_verification_evidence(artifact: dict | None) -> bool:
    if not artifact:
        return False
    checks = artifact.get("checks")
    if not isinstance(checks, list) or not checks:
        return False
    for check in checks:
        if not isinstance(check, dict):
            return False
        if not str(check.get("command", "")).strip():
            return False
        if not str(check.get("output_observed", "")).strip():
            return False
        if str(check.get("result", "")).strip().upper() not in {"PASS", "FAIL"}:
            return False
    return True


def assess_completion(
    tasks: list[dict],
    verifications: list[dict],
    changed_paths: list[str],
    user_message: str,
    workspace_changes_allowed: bool = True,
    runtime_mode: str = "execute",
    plan_artifact_written: bool = False,
) -> dict:
    """Summarize completion quality without deciding whether the run may finish."""
    tasks = clone_tasks(tasks or [])
    verifications = list(verifications or [])
    changed_paths = list(changed_paths or [])
    warnings = []
    hard_blocks = []
    latest_status = latest_verification_status(verifications)
    if str(runtime_mode or "") == "plan":
        if not plan_artifact_written:
            hard_blocks.append("write the active plan file before final answer")
            warnings.append("write the active plan file before final answer")
        return {
            "blocked": False,
            "status": "completed" if plan_artifact_written else "incomplete",
            "hard_blocks": hard_blocks,
            "warnings": warnings,
            "reasons": list(hard_blocks or warnings),
            "tasks": task_counts(tasks),
            "verification_status": latest_status,
            "changed_paths": changed_paths,
            "runtime_mode": "plan",
            "plan_artifact_written": bool(plan_artifact_written),
        }
    progress_expected = expects_workspace_progress(user_message)
    if expects_task_ledger(user_message) and not tasks:
        hard_blocks.append("create a todo list first with todo_write")
        warnings.append("create a todo list first with todo_write")
    if progress_expected and workspace_changes_allowed and not changed_paths:
        hard_blocks.append("make requested workspace changes before final answer")
        warnings.append("make requested workspace changes before final answer")
    open_tasks = [task for task in tasks if task.get("status") in {"pending", "in_progress", "blocked"}]
    if open_tasks:
        warnings.append("complete or unblock all task ledger items")
        if expects_task_ledger(user_message) or changed_paths:
            hard_blocks.append("complete or unblock all task ledger items")
    if requires_verification(user_message) and (changed_paths or progress_expected):
        latest = verifications[-1] if verifications else None
        if latest_status != "passed":
            hard_blocks.append("run a real verification command before final answer")
            warnings.append("run a real verification command before final answer")
        elif not has_structured_verification_evidence(latest):
            warnings.append("record structured verification evidence")
    if open_tasks:
        status = "incomplete"
    elif any("verification" in warning for warning in warnings):
        status = "unverified"
    elif warnings:
        status = "completed_with_warnings"
    else:
        status = "completed"
    return {
        "blocked": False,
        "status": status,
        "hard_blocks": hard_blocks,
        "warnings": warnings,
        "reasons": list(hard_blocks or warnings),
        "tasks": task_counts(tasks),
        "verification_status": latest_status,
        "changed_paths": changed_paths,
    }


def clone_tasks(tasks: list[dict]) -> list[dict]:
    return deepcopy(tasks)
