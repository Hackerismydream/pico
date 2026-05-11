"""Tool execution boundary for Pico runtime."""

import re
from dataclasses import dataclass, field
from typing import Callable

from ..features import completion
from ..tools.registry import is_allowed
from ..tools.shell_safety import is_read_only_shell_command
from ..tools.spec import Effect


@dataclass
class ToolExecutionResult:
    content: str
    metadata: dict
    effects: set[Effect] = field(default_factory=set)


@dataclass(frozen=True)
class ToolPreflightResult:
    allowed: bool = True
    message: str = ""
    code: str = ""
    security_event_type: str = ""
    recovery_message: str = ""
    read_only: bool | None = None
    risk_level: str = ""
    runtime_warnings: tuple[str, ...] = ()

    @classmethod
    def allow(cls, runtime_warnings=()):
        return cls(allowed=True, runtime_warnings=tuple(str(item) for item in runtime_warnings or ()))

    @classmethod
    def reject(
        cls,
        message: str,
        code: str = "invalid_arguments",
        security_event_type: str = "",
        recovery_message: str = "",
        read_only: bool | None = None,
        risk_level: str = "",
    ):
        return cls(
            allowed=False,
            message=str(message),
            code=str(code or "invalid_arguments"),
            security_event_type=str(security_event_type or ""),
            recovery_message=str(recovery_message or ""),
            read_only=read_only,
            risk_level=str(risk_level or ""),
        )


@dataclass
class ToolExecutionContext:
    tools: dict
    allowed_tools: tuple | None = None
    workspace: object | None = None
    read_only: bool = False
    read_only_stall_limit: int = 4
    preflight_tool: Callable | None = None
    is_active_plan_file_write: Callable = lambda name, args: False
    validate_tool: Callable = lambda name, args: None
    tool_example: Callable = lambda name: ""
    tool_rejection_recovery_message: Callable = lambda name, args, code, error_text="": ""
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
    tool_activity_description: Callable = lambda name, args=None: name
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
                "effective_effects": [],
            }
            content = f"error: tool '{name}' is not allowed in this session" if not_allowed else f"error: unknown tool '{name}'"
            return ToolExecutionResult(content=content, metadata=metadata, effects=set())
        effects = _effective_effects(name, args, tool)
        preflight = self._preflight(name, args, tool)
        if not preflight.allowed:
            metadata = {
                "tool_status": "rejected",
                "tool_error_code": preflight.code or "invalid_arguments",
                "security_event_type": preflight.security_event_type,
                "risk_level": preflight.risk_level or ("high" if tool["risky"] else "low"),
                "read_only": bool(preflight.read_only) if preflight.read_only is not None else not tool["risky"],
                "affected_paths": [],
                "workspace_changed": False,
                "diff_summary": [],
                "recovery_message": preflight.recovery_message,
                "effective_effects": _effect_names(effects),
            }
            message = preflight.message
            if preflight.recovery_message:
                message += f"\n{preflight.recovery_message}"
            return ToolExecutionResult(content=message, metadata=metadata, effects=effects)

        runtime_warnings = list(preflight.runtime_warnings or [])
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
                "effective_effects": _effect_names(effects),
                **({"runtime_warnings": runtime_warnings} if runtime_warnings else {}),
                **({"verification": verification} if verification else {}),
                **artifact_metadata,
            }
            return ToolExecutionResult(content=result, metadata=metadata, effects=effects)
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
                "effective_effects": _effect_names(effects),
            }
            return ToolExecutionResult(content=f"error: tool {name} failed: {exc}", metadata=metadata, effects=effects)

    def _preflight(self, name, args, tool) -> ToolPreflightResult:
        if self.context.preflight_tool is not None:
            return self.context.preflight_tool(name, args, tool)
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
            return ToolPreflightResult.reject(
                message=message,
                code=tool_error_code,
                security_event_type=security_event_type,
                recovery_message=recovery,
                read_only=not tool["risky"],
                risk_level="high" if tool["risky"] else "low",
            )
        return ToolPreflightResult.allow()


def _workspace_fingerprint(workspace):
    if workspace is None:
        return ""
    fingerprint = getattr(workspace, "fingerprint", None)
    return fingerprint() if callable(fingerprint) else ""


def _effective_effects(name, args, tool) -> set[Effect]:
    if name == "run_shell" and is_read_only_shell_command(str((args or {}).get("command", ""))):
        return {Effect.PROCESS_READ}
    policy = dict(tool.get("policy", {}) or {})
    effect_values = policy.get("effects") or []
    if effect_values:
        return {Effect(str(effect)) for effect in effect_values}
    return {Effect.WORKSPACE_READ if tool.get("read_only", not tool.get("risky", False)) else Effect.WORKSPACE_WRITE}


def _effect_names(effects: set[Effect]) -> list[str]:
    return sorted(str(effect) for effect in effects)
