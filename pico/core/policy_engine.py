"""Runtime policy decisions for tool requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tool_runner import ToolPreflightResult


@dataclass(frozen=True)
class ToolRequest:
    name: str
    args: dict = field(default_factory=dict)
    tool: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyContext:
    runtime_mode: str
    read_only: bool
    approval_policy: str
    allowed_tools: tuple | None
    write_scope: tuple
    recent_tool_calls: list
    read_ledger: dict
    active_plan_file: str
    tools: dict
    request_paths: tuple[str, ...] = ()
    path_freshness: dict[str, str] = field(default_factory=dict)
    existing_paths: tuple[str, ...] = ()
    approval_required: bool = True
    approval_granted: bool | None = None
    changed_paths: tuple[str, ...] = ()
    latest_verification_status: str = ""
    consecutive_read_only_count: int = 0
    read_only_stall_limit: int = 4
    static_error: str = ""
    static_error_code: str = ""
    security_event_type: str = ""
    tool_example: str = ""


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
    def before_tool(self, context: PolicyContext | Any | None, request: ToolRequest) -> PolicyDecision:
        if context is None:
            return PolicyDecision.allow()
        if not isinstance(context, PolicyContext):
            return self._before_tool_legacy(context, request)
        tool = dict(request.tool or {})
        if context.static_error:
            return self._reject_from_static_error(context, request)
        if _is_repeated_call(context.recent_tool_calls, request.name, request.args):
            return PolicyDecision(
                allowed=False,
                message=f"error: repeated identical tool call for {request.name}; choose a different tool or return a final answer",
                code="repeated_identical_call",
                read_only=not tool.get("risky", False),
                risk_level="high" if tool.get("risky", False) else "low",
            )
        plan_denial = _plan_mode_denial(context, request)
        if plan_denial:
            return plan_denial
        scope_denial = _write_scope_denial(context, request)
        if scope_denial:
            return scope_denial
        read_denial = _prior_read_denial(context, request)
        if read_denial:
            return read_denial
        if tool.get("risky", False) and context.approval_required and not _is_active_plan_file_write(context, request):
            if context.approval_granted is False or context.approval_policy == "never":
                security_event = "read_only_block" if context.read_only else "approval_denied"
                return PolicyDecision(
                    allowed=False,
                    message=f"error: approval denied for {request.name}",
                    code="approval_denied",
                    security_event_type=security_event,
                    read_only=False,
                    risk_level="high",
                )
        warnings = []
        changed_path_stall = _changed_path_read_stall(context, request)
        if changed_path_stall:
            warnings.append(changed_path_stall)
        if (
            request.name not in {"todo_write", "todo_update", "todo_list"}
            and tool.get("read_only", not tool.get("risky", False))
            and context.consecutive_read_only_count >= context.read_only_stall_limit
        ):
            warnings.append(
                "read-only inspection budget exhausted; run a verification command, modify files, or return a final answer"
            )
        return PolicyDecision(allowed=True, runtime_warnings=tuple(warnings))

    def _before_tool_legacy(self, host, request: ToolRequest) -> PolicyDecision:
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

    def _reject_from_static_error(self, context: PolicyContext, request: ToolRequest) -> PolicyDecision:
        message = f"error: invalid arguments for {request.name}: {context.static_error}"
        if context.tool_example:
            message += f"\nexample: {context.tool_example}"
        code = context.static_error_code or _error_code_from_text(context.static_error)
        path = _first_request_path(context, request)
        recovery = _recovery_message(request.name, path, code, context.static_error)
        tool = dict(request.tool or {})
        return PolicyDecision(
            allowed=False,
            message=message,
            code=code,
            security_event_type=context.security_event_type,
            recovery_message=recovery,
            read_only=not tool.get("risky", False),
            risk_level="high" if tool.get("risky", False) else "low",
        )


def _is_repeated_call(recent_tool_calls: list, name: str, args: dict) -> bool:
    if len(recent_tool_calls or []) < 2:
        return False
    recent = list(recent_tool_calls or [])[-2:]
    return all(item.get("name") == name and dict(item.get("args", {}) or {}) == dict(args or {}) for item in recent)


def _is_active_plan_file_write(context: PolicyContext, request: ToolRequest) -> bool:
    if context.runtime_mode != "plan" or request.name not in {"write_file", "patch_file"}:
        return False
    active = str(context.active_plan_file or "")
    path = str((request.args or {}).get("path", "")).strip()
    return bool(active and path == active)


def _plan_mode_denial(context: PolicyContext, request: ToolRequest) -> PolicyDecision | None:
    if context.runtime_mode != "plan":
        return None
    tool = dict(request.tool or {})
    if tool.get("read_only", not tool.get("risky", True)):
        return None
    if _is_active_plan_file_write(context, request):
        return None
    active = context.active_plan_file or "(no active plan file)"
    return PolicyDecision(
        allowed=False,
        message=f"error: plan mode denied: {request.name} can only write the active plan file ({active})",
        code="plan_mode_denied",
        recovery_message=f"Write only the active plan file: {active}.",
        read_only=False,
        risk_level="high" if tool.get("risky", False) else "low",
    )


def _prior_read_denial(context: PolicyContext, request: ToolRequest) -> PolicyDecision | None:
    if _is_active_plan_file_write(context, request):
        return None
    tool = dict(request.tool or {})
    paths = list(context.request_paths or _request_paths(request.name, request.args))
    paths_to_check: list[str] = []
    if dict(tool.get("policy", {}) or {}).get("requires_prior_read"):
        paths_to_check.extend(paths)
    if request.name in {"write_file", "write_files"}:
        paths_to_check.extend([path for path in paths if path in set(context.existing_paths or ())])
    for path in _dedupe(paths_to_check):
        entry = dict((context.read_ledger or {}).get(path, {}) or {})
        if not entry:
            return _prior_read_rejection(request.name, path, "prior_read_required", f"{request.name} requires prior read_file for {path}", tool)
        current = str((context.path_freshness or {}).get(path, ""))
        if current and entry.get("freshness") != current:
            return _prior_read_rejection(request.name, path, "stale_prior_read", f"{request.name} requires a fresh read_file for {path}", tool)
    return None


def _write_scope_denial(context: PolicyContext, request: ToolRequest) -> PolicyDecision | None:
    if request.name not in {"write_file", "write_files", "patch_file"} or not context.write_scope:
        return None
    scopes = [str(scope).strip().rstrip("/") for scope in context.write_scope if str(scope).strip()]
    if not scopes:
        return PolicyDecision(
            allowed=False,
            message="error: invalid arguments for write tool: subagent write_scope is empty",
            code="write_scope_denied",
            read_only=False,
            risk_level="high",
        )
    if "." in scopes:
        return None
    for path in context.request_paths or _request_paths(request.name, request.args):
        if not any(path == scope or path.startswith(f"{scope}/") for scope in scopes):
            return PolicyDecision(
                allowed=False,
                message=f"error: invalid arguments for {request.name}: {path} is outside subagent write_scope ({', '.join(scopes)})",
                code="write_scope_denied",
                read_only=False,
                risk_level="high",
            )
    return None


def _prior_read_rejection(name: str, path: str, code: str, error_text: str, tool: dict) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        message=f"error: invalid arguments for {name}: {error_text}",
        code=code,
        recovery_message=_recovery_message(name, path, code, error_text),
        read_only=not tool.get("risky", False),
        risk_level="high" if tool.get("risky", False) else "low",
    )


def _changed_path_read_stall(context: PolicyContext, request: ToolRequest) -> str:
    if request.name != "read_file" or context.latest_verification_status == "failed":
        return ""
    path = str((request.args or {}).get("path", "") or "")
    if not path or path not in set(context.changed_paths or ()):
        return ""
    if context.consecutive_read_only_count < 2:
        return ""
    return (
        "error: you are rereading a file changed in this run without a failed verification. "
        "Mark the related todo complete, write the next files, run verification, or patch a specific issue."
    )


def _request_paths(name: str, args: dict) -> tuple[str, ...]:
    if name == "write_files":
        return tuple(
            str(item.get("path", "")).strip()
            for item in (args or {}).get("files", []) or []
            if isinstance(item, dict) and str(item.get("path", "")).strip()
        )
    path = str((args or {}).get("path", "")).strip()
    return (path,) if path else ()


def _dedupe(paths: list[str]) -> list[str]:
    unique = []
    for path in paths:
        if path and path not in unique:
            unique.append(path)
    return unique


def _first_request_path(context: PolicyContext, request: ToolRequest) -> str:
    paths = list(context.request_paths or _request_paths(request.name, request.args))
    return paths[0] if paths else ""


def _error_code_from_text(error_text: str) -> str:
    if "requires prior read_file" in error_text:
        return "prior_read_required"
    if "requires a fresh read_file" in error_text:
        return "stale_prior_read"
    if "plan mode denied" in error_text:
        return "plan_mode_denied"
    return "invalid_arguments"


def _recovery_message(name: str, path: str, code: str, error_text: str = "") -> str:
    if code not in {"prior_read_required", "stale_prior_read"}:
        return ""
    if not path:
        return ""
    return (
        f"Runtime recovery: {name} was rejected by the file-safety policy. "
        f'Next tool: read_file with path "{path}", then retry with patch_file or write_file after reading the current contents.'
    )
