"""Runtime policy decisions for tool requests."""

from __future__ import annotations

from dataclasses import dataclass, field

from .tool_runner import ToolPreflightResult


@dataclass(frozen=True)
class ToolRequest:
    name: str
    args: dict = field(default_factory=dict)
    tool: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    message: str = ""
    code: str = ""
    security_event_type: str = ""
    recovery_message: str = ""
    read_only: bool | None = None
    risk_level: str = ""
    runtime_warnings: tuple[str, ...] = ()

    @classmethod
    def allow(cls):
        return cls(allowed=True)

    def to_preflight(self) -> ToolPreflightResult:
        if self.allowed:
            return ToolPreflightResult.allow(runtime_warnings=self.runtime_warnings)
        return ToolPreflightResult.reject(
            message=self.message,
            code=self.code,
            security_event_type=self.security_event_type,
            recovery_message=self.recovery_message,
            read_only=self.read_only,
            risk_level=self.risk_level,
        )


class PolicyEngine:
    def before_tool(self, host, request: ToolRequest) -> PolicyDecision:
        if host is None:
            return PolicyDecision.allow()
        try:
            host.validate_tool(request.name, request.args)
        except Exception as exc:
            return self._reject_from_validation_error(host, request, exc)
        tool = dict(request.tool or {})
        if host.repeated_tool_call(request.name, request.args):
            return PolicyDecision(
                allowed=False,
                message=f"error: repeated identical tool call for {request.name}; choose a different tool or return a final answer",
                code="repeated_identical_call",
                read_only=not tool.get("risky", False),
                risk_level="high" if tool.get("risky", False) else "low",
            )
        if tool.get("risky", False) and not host.is_active_plan_file_write(request.name, request.args) and not host.approve(request.name, request.args):
            return PolicyDecision(
                allowed=False,
                message=f"error: approval denied for {request.name}",
                code="approval_denied",
                security_event_type="read_only_block" if getattr(host, "read_only", False) else "approval_denied",
                read_only=False,
                risk_level="high",
            )
        warnings = []
        changed_path_stall = host.changed_path_read_stall(request.name, request.args)
        if changed_path_stall:
            warnings.append(changed_path_stall)
        if (
            request.name not in {"todo_write", "todo_update", "todo_list"}
            and tool.get("read_only", not tool.get("risky", False))
            and host.consecutive_read_only_tool_count() >= getattr(host, "read_only_stall_limit", 4)
        ):
            warnings.append(
                "read-only inspection budget exhausted; run a verification command, modify files, or return a final answer"
            )
        return PolicyDecision(allowed=True, runtime_warnings=tuple(warnings))

    def _reject_from_validation_error(self, host, request: ToolRequest, exc: Exception) -> PolicyDecision:
        example = host.tool_example(request.name)
        message = f"error: invalid arguments for {request.name}: {exc}"
        if example:
            message += f"\nexample: {example}"
        error_text = str(exc)
        security_event_type = ""
        if "path escapes workspace" in error_text:
            security_event_type = "path_escape"
        elif "blocked shell command" in error_text:
            security_event_type = "shell_command_blocked"
        code = "invalid_arguments"
        if "requires prior read_file" in error_text:
            code = "prior_read_required"
        elif "requires a fresh read_file" in error_text:
            code = "stale_prior_read"
        elif "plan mode denied" in error_text:
            code = "plan_mode_denied"
        recovery = host.tool_rejection_recovery_message(request.name, request.args, code, error_text)
        tool = dict(request.tool or {})
        return PolicyDecision(
            allowed=False,
            message=message,
            code=code,
            security_event_type=security_event_type,
            recovery_message=recovery,
            read_only=not tool.get("risky", False),
            risk_level="high" if tool.get("risky", False) else "low",
        )
