"""Tool execution guardrail used by Pico runtime."""

import re

from .governance import record_governance_decision
from .tool_policy import ToolPolicyChecker
from .tool_result_artifacts import render_tool_result
from .tool_repetition import repeated_tool_call_metadata



def run_tool(agent, name, args):
    tool = agent.tools.get(name)
    if tool is None:
        agent._last_tool_result_metadata = {
            "tool_status": "rejected",
            "tool_error_code": "unknown_tool",
            "security_event_type": "",
            "risk_level": "high",
            "read_only": False,
            "affected_paths": [],
            "workspace_changed": False,
            "diff_summary": [],
        }
        record_governance_decision(agent, name, args, decision="deny", reason_code="unknown_tool", decision_type="tool_lookup")
        return f"error: unknown tool '{name}'"
    try:
        agent.validate_tool(name, args)
    except Exception as exc:
        example = agent.tool_example(name)
        message = f"error: invalid arguments for {name}: {exc}"
        if example:
            message += f"\nexample: {example}"
        security_event_type = "path_escape" if "path escapes workspace" in str(exc) else ""
        agent._last_tool_result_metadata = {
            "tool_status": "rejected",
            "tool_error_code": "invalid_arguments",
            "security_event_type": security_event_type,
            "risk_level": "high" if tool.risky else "low",
            "read_only": tool.read_only,
            "affected_paths": [],
            "workspace_changed": False,
            "diff_summary": [],
        }
        record_governance_decision(agent, name, args, decision="deny", reason_code="invalid_arguments", decision_type="tool_validation")
        return message
    if agent.repeated_tool_call(name, args):
        agent._last_tool_result_metadata = repeated_tool_call_metadata(tool)
        record_governance_decision(agent, name, args, decision="deny", reason_code="repeated_identical_call", decision_type="tool_repetition")
        return f"error: repeated identical tool call for {name}; choose a different tool or return a final answer"
    decision = agent.permission_checker.check(tool, args)
    _emit_permission_decision(agent, tool, args, decision)
    permission_reason = "read_only_violation" if not decision.allowed and getattr(agent, "read_only", False) else decision.reason
    record_governance_decision(agent, name, args, decision=decision.decision, reason_code=permission_reason, decision_type="permission")
    if not decision.allowed:
        agent._last_tool_result_metadata = {
            "tool_status": "rejected",
            "tool_error_code": decision.reason,
            "security_event_type": decision.security_event_type,
            "risk_level": "high" if tool.risky else "low",
            "read_only": tool.read_only,
            "affected_paths": [],
            "workspace_changed": False,
            "diff_summary": [],
        }
        return _permission_error(agent, tool, decision)
    policy = ToolPolicyChecker(agent).check(tool, args)
    _emit_tool_policy_decision(agent, tool, args, policy)
    record_governance_decision(agent, name, args, decision=policy.decision, reason_code=policy.reason, decision_type="tool_policy")
    if not policy.allowed:
        agent._last_tool_result_metadata = {
            "tool_status": "rejected",
            "tool_error_code": policy.reason,
            "security_event_type": "tool_policy",
            "risk_level": "high" if tool.risky else "low",
            "read_only": tool.read_only,
            "affected_paths": [],
            "workspace_changed": False,
            "diff_summary": [],
        }
        agent.record_process_note_for_tool(name, agent._last_tool_result_metadata)
        return policy.message
    before_snapshot = agent.capture_workspace_snapshot() if tool.risky else {}
    after_snapshot = before_snapshot
    try:
        full_result = tool.execute(args).content
        result, artifact_metadata = render_tool_result(agent, name, full_result)
        after_snapshot = agent.capture_workspace_snapshot() if tool.risky else before_snapshot
        affected_paths, diff_summary = agent.diff_workspace_snapshots(before_snapshot, after_snapshot)
        workspace_changed = bool(affected_paths)
        tool_status = "ok"
        tool_error_code = ""
        if name == "run_shell":
            match = re.search(r"exit_code:\s*(-?\d+)", result)
            exit_code = int(match.group(1)) if match else 0
            if exit_code != 0 and workspace_changed:
                tool_status = "partial_success"
                tool_error_code = "tool_partial_success"
            elif exit_code != 0:
                tool_status = "error"
                tool_error_code = "tool_failed"
        agent.update_memory_after_tool(name, args, result)
        agent._last_tool_result_metadata = {
            "tool_status": tool_status,
            "tool_error_code": tool_error_code,
            "security_event_type": "",
            "risk_level": "high" if tool.risky else "low",
            "read_only": tool.read_only,
            "affected_paths": affected_paths,
            "workspace_changed": workspace_changed,
            "workspace_fingerprint": agent.workspace.fingerprint(),
            "diff_summary": diff_summary,
            **artifact_metadata,
        }
        agent.record_process_note_for_tool(name, agent._last_tool_result_metadata)
        return result
    except Exception as exc:
        after_snapshot = agent.capture_workspace_snapshot() if tool.risky else before_snapshot
        affected_paths, diff_summary = agent.diff_workspace_snapshots(before_snapshot, after_snapshot)
        workspace_changed = bool(affected_paths)
        security_event_type = "path_escape" if "path escapes workspace" in str(exc) else ""
        if name == "run_shell" and "sandbox required but unavailable" in str(exc):
            record_governance_decision(agent, name, args, decision="deny", reason_code="sandbox_rejected_command", decision_type="sandbox")
        agent._last_tool_result_metadata = {
            "tool_status": "partial_success" if workspace_changed else "error",
            "tool_error_code": "tool_partial_success" if workspace_changed else "tool_failed",
            "security_event_type": security_event_type,
            "risk_level": "high" if tool.risky else "low",
            "read_only": tool.read_only,
            "affected_paths": affected_paths,
            "workspace_changed": workspace_changed,
            "workspace_fingerprint": agent.workspace.fingerprint(),
            "diff_summary": diff_summary,
        }
        agent.record_process_note_for_tool(name, agent._last_tool_result_metadata)
        return f"error: tool {name} failed: {exc}"


def _emit_permission_decision(agent, tool, args, decision):
    agent.session_event_bus.emit(
        "permission_decision",
        {
            "tool_name": tool.name,
            "decision": decision.decision,
            "reason": decision.reason,
            "security_event_type": decision.security_event_type,
            "tool_profile": agent.active_tool_profile.name,
            "args": args or {},
        },
    )


def _emit_tool_policy_decision(agent, tool, args, decision):
    agent.session_event_bus.emit(
        "tool_policy_decision",
        {"tool_name": tool.name, "decision": decision.decision, "reason": decision.reason, "args": args or {}},
    )


def _permission_error(agent, tool, decision):
    if decision.reason == "plan_mode_path_mismatch":
        return f"error: plan mode can only write the active plan artifact ({agent.plan_mode.plan_path})"
    if decision.reason == "plan_mode_tool_not_allowed":
        return f"error: plan mode only allows read-only tools or writing the active plan artifact ({agent.plan_mode.plan_path})"
    if decision.reason == "write_scope_mismatch":
        return f"error: worker write_scope does not allow {tool.name} on this path"
    if decision.reason in {"approval_denied", "tool_not_allowed"}:
        return f"error: approval denied for {tool.name}"
    return f"error: permission denied for {tool.name}: {decision.reason}"
