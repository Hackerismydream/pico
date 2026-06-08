"""Per-run governance evidence for tool decisions."""


def record_governance_decision(
    agent,
    tool_name,
    args,
    *,
    decision,
    reason_code,
    decision_type,
    source="tool_executor",
):
    task_state = getattr(agent, "current_task_state", None)
    if task_state is None:
        return None
    return agent.emit_trace(
        task_state,
        "governance_decision",
        {
            "decision": str(decision),
            "decision_type": str(decision_type),
            "reason_code": str(reason_code),
            "tool_name": str(tool_name),
            "tool_profile": getattr(agent.active_tool_profile, "name", ""),
            "read_only": bool(getattr(agent, "read_only", False)),
            "args": args or {},
            "source": source,
        },
    )


def reduce_governance_summary(summary, event):
    summary = dict(summary or {})
    decision = str(event.get("decision", ""))
    reason = str(event.get("reason_code", ""))
    key = f"{decision}_count"
    summary[key] = int(summary.get(key, 0) or 0) + 1
    for missing in ("allow_count", "deny_count", "warn_count"):
        summary.setdefault(missing, 0)
    reasons = dict(summary.get("reasons", {}) or {})
    reasons[reason] = reasons.get(reason, 0) + 1
    summary["reasons"] = reasons
    if decision == "deny":
        summary["last_denied_reason"] = reason
    return summary
