"""Read-model projections derived from kernel runtime events."""


def _last_event(events, event_type):
    for event in reversed(events):
        if event.type == event_type:
            return event
    return None


def project_run_id(events):
    for event in events:
        invocation_id = event.payload.get("invocation_id")
        if invocation_id:
            return str(invocation_id)
    return ""


def project_final_answer(events):
    terminal = _last_event(events, "terminal_status")
    if terminal is None or terminal.payload.get("status") != "completed":
        return ""
    final = _last_event(events, "final_answer")
    if final is not None:
        return str(final.payload.get("text", ""))
    output = _last_event(events, "model_output")
    if output is None:
        return ""
    return str(output.payload.get("text", ""))


def project_cli_runtime_events(events):
    lines = []
    for event in events:
        if event.type == "tool_call_requested":
            lines.append(f"tool {event.payload.get('name')} requested")
        elif event.type == "tool_permission_decision":
            name = event.payload.get("name", "")
            decision = event.payload.get("decision", "")
            reason = event.payload.get("reason", "")
            lines.append(f"tool {name} permission {decision}: {reason}")
        elif event.type == "tool_result":
            status = event.payload.get("status", "")
            name = event.payload.get("name", "")
            failure = event.payload.get("failure_classification", "")
            suffix = f" ({failure})" if failure else ""
            lines.append(f"tool {name} {status}{suffix}")
    final_answer = project_final_answer(events)
    if final_answer:
        lines.append(f"final {final_answer}")
    return "\n".join(lines)


def project_trace(events):
    return [
        {
            "event": event.type,
            "created_at": event.created_at,
            "payload": dict(event.payload),
        }
        for event in events
    ]


def project_report(events):
    terminal = _last_event(events, "terminal_status")
    tool_results = [
        {
            "name": event.payload.get("name", ""),
            "status": event.payload.get("status", ""),
            "failure_classification": event.payload.get("failure_classification", ""),
            "content": event.payload.get("content", ""),
        }
        for event in events
        if event.type == "tool_result"
    ]
    provider_calls = [
        {
            "provider": event.payload.get("provider", ""),
            "metadata": dict(event.payload.get("metadata", {}) or {}),
            "step": event.payload.get("step", ""),
        }
        for event in events
        if event.type == "model_output"
    ]
    permission_decisions = [
        {
            "tool_call_id": event.payload.get("tool_call_id", ""),
            "name": event.payload.get("name", ""),
            "decision": event.payload.get("decision", ""),
            "reason": event.payload.get("reason", ""),
            "policy_name": event.payload.get("policy_name", ""),
            "failure_classification": event.payload.get("failure_classification", ""),
        }
        for event in events
        if event.type == "tool_permission_decision"
    ]
    return {
        "run_id": project_run_id(events),
        "status": "unknown" if terminal is None else str(terminal.payload.get("status", "unknown")),
        "final_answer": project_final_answer(events),
        "tool_calls": tool_results,
        "permission_decisions": permission_decisions,
        "provider_calls": provider_calls,
        "terminal_status": {} if terminal is None else dict(terminal.payload),
    }


def project_session(events):
    history = []
    tool_calls = _project_tool_calls(events)
    for event in events:
        if event.type == "user_input":
            history.append({"role": "user", "content": str(event.payload.get("text", ""))})
        elif event.type == "model_output":
            history.append(
                {
                    "role": "assistant",
                    "content": str(event.payload.get("text", "")),
                    "provider": str(event.payload.get("provider", "")),
                    "metadata": dict(event.payload.get("metadata", {}) or {}),
                }
            )
        elif event.type == "tool_result":
            history.append(
                {
                    "role": "tool",
                    "name": str(event.payload.get("name", "")),
                    "tool_call_id": str(event.payload.get("tool_call_id", "")),
                    "status": str(event.payload.get("status", "")),
                    "content": str(event.payload.get("content", "")),
                    "failure_classification": str(event.payload.get("failure_classification", "")),
                }
            )
        elif event.type == "final_answer":
            history.append({"role": "assistant", "content": str(event.payload.get("text", "")), "final": True})
    terminal = _last_event(events, "terminal_status")
    return {
        "projection": "session",
        "run_id": project_run_id(events),
        "status": "unknown" if terminal is None else str(terminal.payload.get("status", "unknown")),
        "history": history,
        "tool_calls": tool_calls,
        "terminal_status": {} if terminal is None else dict(terminal.payload),
    }


def project_export(events):
    terminal = _last_event(events, "terminal_status")
    provider_calls = [
        {
            "provider": event.payload.get("provider", ""),
            "metadata": dict(event.payload.get("metadata", {}) or {}),
            "step": event.payload.get("step", ""),
        }
        for event in events
        if event.type == "model_output"
    ]
    return {
        "artifact_type": "kernel-runtime-export",
        "run_id": project_run_id(events),
        "status": "unknown" if terminal is None else str(terminal.payload.get("status", "unknown")),
        "final_answer": project_final_answer(events),
        "tool_calls": _project_tool_calls(events),
        "provider_calls": provider_calls,
        "terminal_status": {} if terminal is None else dict(terminal.payload),
    }


def _project_tool_calls(events):
    calls = []
    by_id = {}
    for event in events:
        if event.type != "tool_call_requested":
            continue
        tool_call_id = str(event.payload.get("tool_call_id", ""))
        item = {
            "tool_call_id": tool_call_id,
            "name": str(event.payload.get("name", "")),
            "args": dict(event.payload.get("args", {}) or {}),
            "read_only": bool(event.payload.get("read_only", False)),
            "permission": {},
            "result": {},
        }
        calls.append(item)
        by_id[tool_call_id] = item
    for event in events:
        tool_call_id = str(event.payload.get("tool_call_id", ""))
        if tool_call_id not in by_id:
            continue
        if event.type == "tool_permission_decision":
            by_id[tool_call_id]["permission"] = {
                "decision": str(event.payload.get("decision", "")),
                "reason": str(event.payload.get("reason", "")),
                "policy_name": str(event.payload.get("policy_name", "")),
                "failure_classification": str(event.payload.get("failure_classification", "")),
                "available": event.payload.get("available", ""),
            }
        elif event.type == "tool_result":
            by_id[tool_call_id]["result"] = {
                "status": str(event.payload.get("status", "")),
                "content": str(event.payload.get("content", "")),
                "error_message": str(event.payload.get("error_message", "")),
                "failure_classification": str(event.payload.get("failure_classification", "")),
            }
    return calls


def project_terminal_error(events):
    terminal = _last_event(events, "terminal_status")
    if terminal is None:
        return "runtime_error: missing terminal status"
    error_type = str(terminal.payload.get("error_type") or "runtime_error")
    message = str(terminal.payload.get("error_message") or "runtime failed")
    return f"{error_type}: {message}"
