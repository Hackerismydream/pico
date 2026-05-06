"""Tool execution boundary for Pico runtime."""

import re
from dataclasses import dataclass, field
from typing import Callable

from ..features import completion
from ..tools.registry import is_allowed


@dataclass
class ToolExecutionResult:
    content: str
    metadata: dict


@dataclass
class ToolExecutionContext:
    tools: dict
    allowed_tools: tuple | None = None
    workspace: object | None = None
    read_only: bool = False
    read_only_stall_limit: int = 4
    is_active_plan_file_write: Callable = lambda name, args: False
    validate_tool: Callable = lambda name, args: None
    tool_example: Callable = lambda name: ""
    tool_rejection_recovery_message: Callable = lambda name, args, code, error_text="": ""
    changed_path_read_stall: Callable = lambda name, args: ""
    repeated_tool_call: Callable = lambda name, args: False
    consecutive_read_only_tool_count: Callable = lambda: 0
    approve: Callable = lambda name, args: True
    capture_workspace_snapshot: Callable = lambda: {}
    materialize_tool_result: Callable = lambda name, args, raw_result, max_chars: (
        str(raw_result),
        {
            "artifact_relpath": "",
            "artifact_chars": 0,
            "result_raw_chars": len(str(raw_result)),
            "result_rendered_chars": min(len(str(raw_result)), int(max_chars or 4000)),
        },
    )
    diff_workspace_snapshots: Callable = lambda before, after: ([], [])
    update_memory_after_tool: Callable = lambda name, args, result: None
    update_tool_policy_after_tool: Callable = lambda name, args, result, status: None
    record_process_note_for_tool: Callable = lambda name, metadata: None
    tool_activity_description: Callable = lambda name, args=None: name
    emit_trace: Callable = lambda *args, **kwargs: None
    extra_metadata: dict = field(default_factory=dict)


class ToolRunner:
    def __init__(self, context: ToolExecutionContext):
        self.context = context

    def run(self, name, args):
        args = args or {}
        tool = self.context.tools.get(name)
        if tool is None:
            not_allowed = self.context.allowed_tools is not None and not is_allowed(self.context.allowed_tools, name)
            metadata = {
                "tool_status": "rejected",
                "tool_error_code": "tool_not_allowed" if not_allowed else "unknown_tool",
                "security_event_type": "",
                "risk_level": "high",
                "read_only": False,
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
            }
            content = f"error: tool '{name}' is not allowed in this session" if not_allowed else f"error: unknown tool '{name}'"
            return ToolExecutionResult(content=content, metadata=metadata)
        try:
            self.context.validate_tool(name, args)
        except Exception as exc:
            example = self.context.tool_example(name)
            message = f"error: invalid arguments for {name}: {exc}"
            if example:
                message += f"\nexample: {example}"
            error_text = str(exc)
            security_event_type = ""
            if "path escapes workspace" in error_text:
                security_event_type = "path_escape"
            elif "blocked shell command" in error_text:
                security_event_type = "shell_command_blocked"
            tool_error_code = "invalid_arguments"
            if "requires prior read_file" in error_text:
                tool_error_code = "prior_read_required"
            elif "requires a fresh read_file" in error_text:
                tool_error_code = "stale_prior_read"
            elif "plan mode denied" in error_text:
                tool_error_code = "plan_mode_denied"
            recovery = self.context.tool_rejection_recovery_message(name, args, tool_error_code, error_text)
            if recovery:
                message += f"\n{recovery}"
            metadata = {
                "tool_status": "rejected",
                "tool_error_code": tool_error_code,
                "security_event_type": security_event_type,
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": not tool["risky"],
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
                "recovery_message": recovery,
            }
            return ToolExecutionResult(content=message, metadata=metadata)

        runtime_warnings = []
        changed_path_stall = self.context.changed_path_read_stall(name, args)
        if changed_path_stall:
            runtime_warnings.append(changed_path_stall)
        if self.context.repeated_tool_call(name, args):
            metadata = {
                "tool_status": "rejected",
                "tool_error_code": "repeated_identical_call",
                "security_event_type": "",
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": not tool["risky"],
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
            }
            return ToolExecutionResult(
                content=f"error: repeated identical tool call for {name}; choose a different tool or return a final answer",
                metadata=metadata,
            )
        if (
            name not in {"todo_write", "todo_update", "todo_list"}
            and tool.get("read_only", not tool["risky"])
            and self.context.consecutive_read_only_tool_count() >= self.context.read_only_stall_limit
        ):
            runtime_warnings.append(
                "read-only inspection budget exhausted; run a verification command, modify files, or return a final answer"
            )
        if tool["risky"] and not self.context.is_active_plan_file_write(name, args) and not self.context.approve(name, args):
            metadata = {
                "tool_status": "rejected",
                "tool_error_code": "approval_denied",
                "security_event_type": "read_only_block" if self.context.read_only else "approval_denied",
                "risk_level": "high",
                "read_only": False,
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
            }
            return ToolExecutionResult(content=f"error: approval denied for {name}", metadata=metadata)

        before_snapshot = self.context.capture_workspace_snapshot() if tool["risky"] else {}
        after_snapshot = before_snapshot
        try:
            raw_result = str(tool["run"](args))
            result, artifact_metadata = self.context.materialize_tool_result(
                name,
                args,
                raw_result,
                int(tool.get("policy", {}).get("max_result_chars", 4000)),
            )
            after_snapshot = self.context.capture_workspace_snapshot() if tool["risky"] else before_snapshot
            affected_paths, diff_summary = self.context.diff_workspace_snapshots(before_snapshot, after_snapshot)
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
            verification = completion.verification_from_shell(str(args.get("command", "")), result) if name == "run_shell" else None
            self.context.update_memory_after_tool(name, args, result)
            self.context.update_tool_policy_after_tool(name, args, raw_result, tool_status)
            metadata = {
                "tool_status": tool_status,
                "tool_error_code": tool_error_code,
                "security_event_type": "",
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": bool(tool.get("read_only", not tool["risky"])),
                "activity": self.context.tool_activity_description(name, args),
                "affected_paths": affected_paths,
                "workspace_changed": workspace_changed,
                "workspace_fingerprint": _workspace_fingerprint(self.context.workspace),
                "diff_summary": diff_summary,
                **({"runtime_warnings": runtime_warnings} if runtime_warnings else {}),
                **({"verification": verification} if verification else {}),
                **artifact_metadata,
            }
            self.context.record_process_note_for_tool(name, metadata)
            return ToolExecutionResult(content=result, metadata=metadata)
        except Exception as exc:
            after_snapshot = self.context.capture_workspace_snapshot() if tool["risky"] else before_snapshot
            affected_paths, diff_summary = self.context.diff_workspace_snapshots(before_snapshot, after_snapshot)
            workspace_changed = bool(affected_paths)
            security_event_type = "path_escape" if "path escapes workspace" in str(exc) else ""
            metadata = {
                "tool_status": "partial_success" if workspace_changed else "error",
                "tool_error_code": "tool_partial_success" if workspace_changed else "tool_failed",
                "security_event_type": security_event_type,
                "risk_level": "high" if tool["risky"] else "low",
                "read_only": bool(tool.get("read_only", not tool["risky"])),
                "activity": self.context.tool_activity_description(name, args),
                "affected_paths": affected_paths,
                "workspace_changed": workspace_changed,
                "workspace_fingerprint": _workspace_fingerprint(self.context.workspace),
                "diff_summary": diff_summary,
            }
            self.context.record_process_note_for_tool(name, metadata)
            return ToolExecutionResult(content=f"error: tool {name} failed: {exc}", metadata=metadata)


def _workspace_fingerprint(workspace):
    if workspace is None:
        return ""
    fingerprint = getattr(workspace, "fingerprint", None)
    return fingerprint() if callable(fingerprint) else ""
