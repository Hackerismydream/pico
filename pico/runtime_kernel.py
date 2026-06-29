"""First narrow runtime-kernel path.

This module proves one vertical path:
CLI adapter -> RuntimeRunner/InvocationContext -> AgentFlow/ModelAdapter ->
ToolRuntime -> RuntimeEvent ledger -> projection.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid

from . import tools as toolkit
from .runtime_projections import (
    project_cli_runtime_events as project_cli_runtime_events,
    project_export as project_export,
    project_final_answer as project_final_answer,
    project_report as project_report,
    project_run_id as project_run_id,
    project_session as project_session,
    project_terminal_error as project_terminal_error,
    project_trace as project_trace,
)
from .tool_context import ToolContext
from .workspace import clip


def _now():
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class RuntimeEvent:
    type: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=_now)


class RuntimeEventLedger:
    def __init__(self):
        self._events = []

    def append(self, event_type, **payload):
        event = RuntimeEvent(type=str(event_type), payload=dict(payload))
        self._events.append(event)
        return event

    @property
    def events(self):
        return list(self._events)


def runtime_event_to_dict(event):
    return {
        "type": event.type,
        "created_at": event.created_at,
        "payload": dict(event.payload),
    }


def runtime_event_from_dict(payload):
    return RuntimeEvent(
        type=str(payload.get("type", "")),
        created_at=str(payload.get("created_at", "")),
        payload=dict(payload.get("payload", {}) or {}),
    )


@dataclass(frozen=True)
class InvocationContext:
    user_message: str
    workspace_root: str
    max_new_tokens: int = 512
    max_steps: int = 6
    invocation_id: str = field(default_factory=lambda: _new_id("invocation"))


@dataclass(frozen=True)
class ModelResult:
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ModelFailure:
    error_type: str
    message: str
    provider: str


class ModelAdapter:
    def __init__(self, model_client):
        self.model_client = model_client

    def complete(self, prompt, max_new_tokens):
        try:
            text = self.model_client.complete(prompt, max_new_tokens)
        except Exception as exc:
            return ModelFailure(
                error_type="provider_error",
                message=str(exc),
                provider=self.provider_name(),
            )
        return ModelResult(
            text=str(text),
            metadata=dict(getattr(self.model_client, "last_completion_metadata", {}) or {}),
        )

    def provider_name(self):
        model = getattr(self.model_client, "model", "")
        client_name = self.model_client.__class__.__name__
        if model:
            return f"{client_name}:{model}"
        return client_name


@dataclass(frozen=True)
class ParsedToolCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ParsedFinalAnswer:
    text: str


@dataclass(frozen=True)
class ParsedRetry:
    message: str


@dataclass(frozen=True)
class ToolPermissionDecision:
    decision: str
    reason: str
    policy_name: str
    failure_classification: str = ""


class ToolPermissionPolicy:
    def __init__(self, mode, reason):
        self.mode = str(mode)
        self.reason = str(reason)
        if self.mode not in {"allow", "deny", "requires_decision"}:
            raise ValueError(f"unknown tool permission policy mode: {self.mode}")

    @classmethod
    def allow_readonly(cls, reason="read-only tools are allowed"):
        return cls("allow", reason)

    @classmethod
    def deny_all(cls, reason="tool use is denied by policy"):
        return cls("deny", reason)

    @classmethod
    def require_decision(cls, reason="tool use requires an explicit permission decision"):
        return cls("requires_decision", reason)

    def decide(self, name, args, *, read_only, available):
        del args
        if not available or not read_only:
            return ToolPermissionDecision(
                decision="deny",
                reason=f"tool '{name}' is not available in the kernel read-only runtime",
                policy_name="kernel_readonly_tool_policy",
                failure_classification="tool_not_allowed",
            )
        if self.mode == "allow":
            return ToolPermissionDecision(
                decision="allow",
                reason=self.reason,
                policy_name="allow_readonly",
            )
        if self.mode == "deny":
            return ToolPermissionDecision(
                decision="deny",
                reason=self.reason,
                policy_name="deny_all",
                failure_classification="permission_denied",
            )
        return ToolPermissionDecision(
            decision="requires_decision",
            reason=self.reason,
            policy_name="requires_decision",
            failure_classification="permission_required",
        )


def parse_model_message(raw):
    raw = str(raw)
    tool_match = re.search(r"<tool>(?P<body>.*?)</tool>", raw, re.S)
    final_match = re.search(r"<final>(?P<body>.*?)</final>", raw, re.S)
    if tool_match and (not final_match or tool_match.start() < final_match.start()):
        try:
            payload = json.loads(tool_match.group("body"))
        except Exception:
            return ParsedRetry("model returned malformed tool JSON")
        if not isinstance(payload, dict):
            return ParsedRetry("tool payload must be a JSON object")
        name = str(payload.get("name", "")).strip()
        if not name:
            return ParsedRetry("tool payload is missing a tool name")
        args = payload.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return ParsedRetry("tool args must be a JSON object")
        return ParsedToolCall(name=name, args=args)
    if final_match:
        final = final_match.group("body").strip()
        if final:
            return ParsedFinalAnswer(final)
        return ParsedRetry("model returned an empty <final> answer")
    text = raw.strip()
    if text:
        return ParsedFinalAnswer(text)
    return ParsedRetry("model returned an empty response")


class ModelHistoryProjector:
    def project(self, context, events):
        tool_results = [
            event.payload
            for event in events
            if event.type == "tool_result" and event.payload.get("invocation_id") == context.invocation_id
        ]
        lines = [
            context.user_message,
            "",
            "Kernel runtime protocol:",
            '- To inspect the workspace, reply with <tool>{"name":"read_file","args":{"path":"README.md"}}</tool>.',
            '- Available read-only tools: read_file, list_files, search.',
            "- To answer, reply with <final>your answer</final>.",
        ]
        if not tool_results:
            return "\n".join(lines)

        lines.extend(["", "Runtime tool results:"])
        for result in tool_results:
            normalized = {
                "tool_call_id": result.get("tool_call_id", ""),
                "name": result.get("name", ""),
                "status": result.get("status", ""),
                "failure_classification": result.get("failure_classification", ""),
                "result": result.get("content", ""),
            }
            if result.get("error_message"):
                normalized["error_message"] = result["error_message"]
            lines.append(json.dumps(normalized, ensure_ascii=True, sort_keys=True))
        lines.extend(
            [
                "",
                "Use the normalized tool result above. Reply with <final>your answer</final>.",
            ]
        )
        return "\n".join(lines)


class ToolRuntime:
    READ_ONLY_TOOL_NAMES = frozenset({"list_files", "read_file", "search"})

    def __init__(self, workspace_root, tool_registry=None, permission_policy=None):
        self.root = Path(workspace_root).resolve()
        registry = self._build_readonly_registry() if tool_registry is None else tool_registry
        self.tool_registry = dict(registry)
        self.permission_policy = permission_policy or ToolPermissionPolicy.allow_readonly()

    def _build_readonly_registry(self):
        context = self._tool_context()
        return {
            "list_files": {
                **toolkit.BASE_TOOL_SPECS["list_files"],
                "run": lambda args: toolkit.tool_list_files(context, args),
            },
            "read_file": {
                **toolkit.BASE_TOOL_SPECS["read_file"],
                "run": lambda args: toolkit.tool_read_file(context, args),
            },
            "search": {
                **toolkit.BASE_TOOL_SPECS["search"],
                "run": lambda args: toolkit.tool_search(context, args),
            },
        }

    def _resolve_workspace_path(self, raw_path):
        path = Path(raw_path)
        path = path if path.is_absolute() else self.root / path
        resolved = path.resolve()
        if os.path.commonpath([str(self.root), str(resolved)]) != str(self.root):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return resolved

    def execute(self, tool_call, context, ledger):
        tool_call_id = _new_id("tool")
        name = str(tool_call.name)
        args = dict(tool_call.args)
        tool = self.tool_registry.get(name)
        is_read_only = name in self.READ_ONLY_TOOL_NAMES
        ledger.append(
            "tool_call_requested",
            invocation_id=context.invocation_id,
            tool_call_id=tool_call_id,
            name=name,
            args=args,
            read_only=is_read_only,
        )

        decision = self.permission_policy.decide(
            name,
            args,
            read_only=is_read_only,
            available=tool is not None,
        )
        self._record_permission_decision(
            context,
            ledger,
            tool_call_id,
            name,
            args,
            is_read_only,
            tool is not None,
            decision,
        )
        if decision.decision == "deny":
            self._record_permission_result(
                context,
                ledger,
                tool_call_id,
                name,
                args,
                status="denied",
                decision=decision,
            )
            return
        if decision.decision == "requires_decision":
            self._record_permission_result(
                context,
                ledger,
                tool_call_id,
                name,
                args,
                status="requires_decision",
                decision=decision,
            )
            return

        try:
            self._validate_tool_args(name, args)
        except Exception as exc:
            failure_classification = "path_escape" if "path escapes workspace" in str(exc) else "invalid_arguments"
            self._record_rejection(
                context,
                ledger,
                tool_call_id,
                name,
                args,
                failure_classification=failure_classification,
                message=str(exc),
            )
            return

        ledger.append(
            "tool_argument_validation",
            invocation_id=context.invocation_id,
            tool_call_id=tool_call_id,
            name=name,
            status="ok",
        )
        try:
            content = clip(tool["run"](args))
        except Exception as exc:
            failure_classification = "path_escape" if "path escapes workspace" in str(exc) else "tool_failed"
            ledger.append(
                "tool_result",
                invocation_id=context.invocation_id,
                tool_call_id=tool_call_id,
                name=name,
                args=args,
                status="error",
                content=f"error: tool {name} failed: {exc}",
                error_message=str(exc),
                failure_classification=failure_classification,
                read_only=True,
            )
            return

        ledger.append(
            "tool_result",
            invocation_id=context.invocation_id,
            tool_call_id=tool_call_id,
            name=name,
            args=args,
            status="ok",
            content=content,
            failure_classification="",
            read_only=True,
        )

    def _record_permission_decision(self, context, ledger, tool_call_id, name, args, read_only, available, decision):
        ledger.append(
            "tool_permission_decision",
            invocation_id=context.invocation_id,
            tool_call_id=tool_call_id,
            name=name,
            args=args,
            decision=decision.decision,
            reason=decision.reason,
            policy_name=decision.policy_name,
            failure_classification=decision.failure_classification,
            read_only=read_only,
            available=available,
        )

    def _record_permission_result(self, context, ledger, tool_call_id, name, args, status, decision):
        ledger.append(
            "tool_result",
            invocation_id=context.invocation_id,
            tool_call_id=tool_call_id,
            name=name,
            args=args,
            status=status,
            content=f"permission {status}: {decision.reason}",
            error_message=decision.reason,
            failure_classification=decision.failure_classification,
            read_only=name in self.READ_ONLY_TOOL_NAMES,
        )

    def _validate_tool_args(self, name, args):
        toolkit.validate_tool(self._tool_context(), name, args)
        if name == "search" and not self._resolve_workspace_path(args.get("path", ".")).exists():
            raise ValueError("path does not exist")

    def _tool_context(self):
        return ToolContext(
            root=self.root,
            path_resolver=self._resolve_workspace_path,
            shell_env_provider=lambda: {"PWD": str(self.root)},
            depth=0,
            max_depth=0,
            spawn_delegate=lambda args: "delegate is unavailable in the kernel read-only runtime",
        )

    def _record_rejection(self, context, ledger, tool_call_id, name, args, failure_classification, message):
        ledger.append(
            "tool_argument_validation",
            invocation_id=context.invocation_id,
            tool_call_id=tool_call_id,
            name=name,
            status="failed",
            error_message=message,
            failure_classification=failure_classification,
        )
        ledger.append(
            "tool_result",
            invocation_id=context.invocation_id,
            tool_call_id=tool_call_id,
            name=name,
            args=args,
            status="error",
            content=f"error: {message}",
            error_message=message,
            failure_classification=failure_classification,
            read_only=True,
        )


class AgentFlow:
    def __init__(self, model_adapter, tool_runtime=None, history_projector=None):
        self.model_adapter = model_adapter
        self.tool_runtime = tool_runtime
        self.history_projector = history_projector or ModelHistoryProjector()

    def run(self, context, ledger):
        for step in range(max(1, int(context.max_steps))):
            prompt = self.history_projector.project(context, ledger.events)
            result = self.model_adapter.complete(prompt, context.max_new_tokens)
            if isinstance(result, ModelFailure):
                ledger.append(
                    "terminal_status",
                    invocation_id=context.invocation_id,
                    status="failed",
                    error_type=result.error_type,
                    error_message=result.message,
                    provider=result.provider,
                )
                return

            ledger.append(
                "model_output",
                invocation_id=context.invocation_id,
                text=result.text,
                metadata=result.metadata,
                provider=self.model_adapter.provider_name(),
                step=step + 1,
            )
            parsed = parse_model_message(result.text)
            if isinstance(parsed, ParsedFinalAnswer):
                ledger.append(
                    "final_answer",
                    invocation_id=context.invocation_id,
                    text=parsed.text,
                )
                ledger.append(
                    "terminal_status",
                    invocation_id=context.invocation_id,
                    status="completed",
                )
                return
            if isinstance(parsed, ParsedRetry):
                ledger.append(
                    "runtime_notice",
                    invocation_id=context.invocation_id,
                    notice_type="model_parse_error",
                    message=parsed.message,
                )
                continue
            if self.tool_runtime is None:
                ledger.append(
                    "terminal_status",
                    invocation_id=context.invocation_id,
                    status="failed",
                    error_type="tool_runtime_missing",
                    error_message="model requested a tool but no ToolRuntime is configured",
                    provider=self.model_adapter.provider_name(),
                )
                return
            self.tool_runtime.execute(parsed, context, ledger)
        ledger.append(
            "terminal_status",
            invocation_id=context.invocation_id,
            status="failed",
            error_type="step_limit_reached",
            error_message="kernel runtime reached max_steps before a final answer",
            provider=self.model_adapter.provider_name(),
        )

    @staticmethod
    def _build_no_tool_prompt(context):
        return str(context.user_message)


@dataclass(frozen=True)
class RuntimeResult:
    events: list[RuntimeEvent]

    @property
    def status(self):
        terminal = _last_event(self.events, "terminal_status")
        if terminal is None:
            return "unknown"
        return str(terminal.payload.get("status", "unknown"))

    @property
    def final_answer(self):
        return project_final_answer(self.events)

    @property
    def error_type(self):
        terminal = _last_event(self.events, "terminal_status")
        if terminal is None:
            return ""
        return str(terminal.payload.get("error_type", ""))

    @property
    def error_message(self):
        terminal = _last_event(self.events, "terminal_status")
        if terminal is None:
            return ""
        return str(terminal.payload.get("error_message", ""))


class RuntimeRunner:
    def __init__(self, model_client=None, model_adapter=None, tool_runtime=None):
        if model_adapter is None:
            if model_client is None:
                raise ValueError("model_client or model_adapter is required")
            model_adapter = ModelAdapter(model_client)
        self.model_adapter = model_adapter
        self.tool_runtime = tool_runtime

    def run(self, context):
        ledger = RuntimeEventLedger()
        ledger.append(
            "invocation_start",
            invocation_id=context.invocation_id,
            workspace_root=context.workspace_root,
        )
        ledger.append(
            "user_input",
            invocation_id=context.invocation_id,
            text=context.user_message,
        )
        tool_runtime = self.tool_runtime
        if tool_runtime is None:
            tool_runtime = ToolRuntime(
                context.workspace_root,
                permission_policy=ToolPermissionPolicy.deny_all(
                    "kernel runtime requires an explicit tool permission policy"
                ),
            )
        AgentFlow(self.model_adapter, tool_runtime=tool_runtime).run(context, ledger)
        return RuntimeResult(events=ledger.events)


def _last_event(events, event_type):
    for event in reversed(events):
        if event.type == event_type:
            return event
    return None
