"""First narrow runtime-kernel path.

This module is intentionally small. It proves one vertical path:
CLI adapter -> RuntimeRunner/InvocationContext -> AgentFlow/ModelAdapter ->
RuntimeEvent ledger -> projection.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


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


@dataclass(frozen=True)
class InvocationContext:
    user_message: str
    workspace_root: str
    max_new_tokens: int = 512
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


class AgentFlow:
    def __init__(self, model_adapter):
        self.model_adapter = model_adapter

    def run(self, context, ledger):
        prompt = self._build_no_tool_prompt(context)
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
        )
        ledger.append(
            "terminal_status",
            invocation_id=context.invocation_id,
            status="completed",
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
    def __init__(self, model_client=None, model_adapter=None):
        if model_adapter is None:
            if model_client is None:
                raise ValueError("model_client or model_adapter is required")
            model_adapter = ModelAdapter(model_client)
        self.agent_flow = AgentFlow(model_adapter)

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
        self.agent_flow.run(context, ledger)
        return RuntimeResult(events=ledger.events)


def _last_event(events, event_type):
    for event in reversed(events):
        if event.type == event_type:
            return event
    return None


def project_final_answer(events):
    terminal = _last_event(events, "terminal_status")
    if terminal is None or terminal.payload.get("status") != "completed":
        return ""
    output = _last_event(events, "model_output")
    if output is None:
        return ""
    return str(output.payload.get("text", ""))


def project_terminal_error(events):
    terminal = _last_event(events, "terminal_status")
    if terminal is None:
        return "runtime_error: missing terminal status"
    error_type = str(terminal.payload.get("error_type") or "runtime_error")
    message = str(terminal.payload.get("error_message") or "runtime failed")
    return f"{error_type}: {message}"
