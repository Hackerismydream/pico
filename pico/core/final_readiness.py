"""Final-answer readiness gate."""

import hashlib


VALID_MODES = {"off", "warn", "soft", "strict"}
CONTEXT_HARD_PRESSURE_RATIO = 0.95
UNRESOLVED_TODO_STATUS = {"pending", "in_progress"}
HARD_REASONS = {
    "changed_paths_without_verification", "failed_verification",
    "governance_denial", "partial_success_workspace_changed",
}


def evaluate_final_readiness(task_state, mode):
    mode = str(mode or "warn")
    if mode not in VALID_MODES:
        mode = "warn"
    reasons = _readiness_reasons(task_state)
    signature = _reason_signature(reasons)
    state = _state(task_state)
    reminded = set(state.get("reminded_reason_signatures", []))
    already_sent = bool(signature and signature in reminded)
    decision = "allow"
    action = "none"
    if reasons and mode == "warn":
        decision = "warn"
    elif reasons and mode == "soft":
        decision, action = ("warn", "none") if already_sent else ("remind", "runtime_notice")
        if not already_sent:
            reminded.add(signature)
    elif reasons and mode == "strict":
        decision, action = (
            ("block", "block") if any(reason in HARD_REASONS for reason in reasons) else ("warn", "none")
        )
    state["reminded_reason_signatures"] = sorted(reminded)
    return {
        "mode": mode,
        "decision": decision,
        "reasons": reasons,
        "reason_signature": signature,
        "reminder_already_sent": already_sent,
        "action": action,
    }


def readiness_notice(decision):
    reasons = ", ".join(decision.get("reasons", [])) or "readiness warning"
    if decision.get("action") == "block":
        return f"Final answer blocked by runtime readiness gate: {reasons}."
    return ("Before final answer, address this runtime readiness issue: "
            f"{reasons}. If the current answer is still correct, return final again.")


def reduce_final_readiness_summary(summary, event):
    summary = dict(summary or {})
    decision = str(event.get("decision", ""))
    summary[f"{decision}_count"] = int(summary.get(f"{decision}_count", 0) or 0) + 1
    for missing in ("allow_count", "warn_count", "remind_count", "block_count"):
        summary.setdefault(missing, 0)
    summary["last_decision"] = decision
    summary["last_reasons"] = list(event.get("reasons", []) or [])
    return summary


def _readiness_reasons(task_state):
    summaries = task_state.evidence_summaries or {}
    reasons = []
    verification = dict(summaries.get("verification_signal", {}) or {})
    if task_state.changed_paths and verification.get("state") != "passed":
        reasons.append("changed_paths_without_verification")
    if verification.get("state") == "failed":
        reasons.append("failed_verification")
    if _has_partial_success_workspace_change(task_state):
        reasons.append("partial_success_workspace_changed")
    governance = dict(summaries.get("governance_summary", {}) or {})
    if int(governance.get("deny_count", 0) or 0):
        reasons.append("governance_denial")
    if _has_unresolved_high_priority_todo(task_state):
        reasons.append("unresolved_high_priority_todo")
    context = dict(summaries.get("context_budget_summary", {}) or {})
    if _context_pressure_without_reduction(context):
        reasons.append("context_pressure_without_reduction")
    return reasons


def _reason_signature(reasons):
    if not reasons:
        return ""
    return hashlib.sha256("|".join(sorted(reasons)).encode("utf-8")).hexdigest()[:16]


def _state(task_state):
    summaries = dict(task_state.evidence_summaries or {})
    state = dict(summaries.get("final_readiness_state", {}) or {})
    summaries["final_readiness_state"] = state
    task_state.evidence_summaries = summaries
    return state

def _has_unresolved_high_priority_todo(task_state):
    latest = {}
    for change in task_state.todo_changes or []:
        todo = dict(change.get("todo", {}) or {})
        todo_id = str(todo.get("id", ""))
        if todo_id:
            latest[todo_id] = todo
    return any(todo.get("priority") == "high" and todo.get("status") in UNRESOLVED_TODO_STATUS for todo in latest.values())


def _has_partial_success_workspace_change(task_state):
    return any(item.get("status") == "partial_success" and item.get("workspace_changed") is True for item in task_state.runtime_reminders or [])


def _context_pressure_without_reduction(context):
    try:
        pressure = float(context.get("pressure_ratio", 0) or 0)
    except (TypeError, ValueError):
        pressure = 0.0
    reductions = context.get("reductions", []) or []
    return pressure >= CONTEXT_HARD_PRESSURE_RATIO and not any(int(item.get("saved_chars", 0) or 0) > 0 for item in reductions)
