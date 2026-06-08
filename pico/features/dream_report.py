import difflib
from pathlib import Path

from ..core.workspace import clip
from .dream_lint import BASE64_LIKE_PATTERN, SECRET_VALUE_PATTERN
from .dream_store import collect_non_runtime_files


def redact_sensitive_text(text):
    text = SECRET_VALUE_PATTERN.sub("<redacted>", str(text))
    return BASE64_LIKE_PATTERN.sub("<redacted>", text)


def write_dream_diff(before_root, candidate_root, diff_path):
    before = collect_non_runtime_files(before_root)
    after = collect_non_runtime_files(candidate_root)
    lines = []
    for relative in sorted(set(before) | set(after)):
        old_lines = before.get(relative, "").splitlines()
        new_lines = after.get(relative, "").splitlines()
        if old_lines == new_lines:
            continue
        lines.extend(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"official/{relative}",
                tofile=f"candidate/{relative}",
                lineterm="",
            )
        )
        lines.append("\n")
    diff_path = Path(diff_path)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_text = redact_sensitive_text("\n".join(lines).rstrip() + ("\n" if lines else ""))
    diff_path.write_text(diff_text, encoding="utf-8")
    return sorted(relative for relative in set(before) | set(after) if before.get(relative) != after.get(relative))


def write_dream_report(task, lint_result, changed_files, model_result):
    report_path = Path(task["report_path"])
    lines = [
        f"# Dream Report: {task['id']}",
        "",
        f"- trigger: {task['trigger']}",
        f"- status: {task['status']}",
        f"- candidate: {task['candidate_store']}",
        f"- lint: {lint_result['status']}",
        "",
        "## Inputs",
    ]
    for session_id in task.get("input_sessions", []):
        lines.append(f"- session:{session_id}")
    if not task.get("input_sessions"):
        lines.append("- none")
    lines.extend(["", "## Changed files"])
    for path in changed_files:
        lines.append(f"- {path}")
    if not changed_files:
        lines.append("- none")
    lines.extend(["", "## Lint"])
    for issue in lint_result.get("errors", []):
        lines.append(f"- error:{issue['code']} {issue.get('path', '')}".rstrip())
    for warning in lint_result.get("warnings", []):
        lines.append(f"- warning:{warning['code']} {warning.get('path', '')}".rstrip())
    if not lint_result.get("errors") and not lint_result.get("warnings"):
        lines.append("- passed")
    lines.extend(["", "## Model result", redact_sensitive_text(str(model_result).strip() or "(empty)")])
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def dream_status_text_for_task(task):
    lines = [
        f"dream: {task.get('id', '')}",
        f"status: {task.get('status', 'unknown')}",
        f"lint: {task.get('lint_status', 'unknown')}",
    ]
    for issue in task.get("lint_errors", []):
        lines.append(f"error: {issue.get('code', '')} {issue.get('path', '')}".rstrip())
    for warning in task.get("lint_warnings", []):
        lines.append(f"warning: {warning.get('code', '')} {warning.get('path', '')}".rstrip())
    return "\n".join(lines)


def dream_review_text(memory_dir, task_id):
    from .memory import load_dream_task

    task = load_dream_task(memory_dir, task_id)
    if not task:
        return f"error: dream task not found: {task_id}"
    parts = [
        dream_status_text_for_task(task),
        "",
        "Changed files:",
    ]
    for path in task.get("changed_files", []):
        parts.append(f"- {path}")
    if not task.get("changed_files"):
        parts.append("- none")
    diff_path = Path(task.get("diff_path", ""))
    if diff_path.exists():
        diff = clip(redact_sensitive_text(diff_path.read_text(encoding="utf-8", errors="replace")), 4000)
        parts.extend(["", "Diff:", diff or "(empty)"])
    return "\n".join(parts)
