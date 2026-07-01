"""Runtime event contracts and compatibility adapters."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


RUNTIME_EVENT_SCHEMA_VERSION = 2

RUNTIME_EVENT_KINDS = frozenset(
    {
        "invocation_start",
        "user_input",
        "model_output",
        "model_failure",
        "tool_call_requested",
        "tool_permission_decision",
        "tool_argument_validation",
        "tool_result",
        "final_answer",
        "terminal_status",
    }
)

RUNTIME_EVENT_STATUSES = frozenset(
    {
        "started",
        "completed",
        "ok",
        "failed",
        "error",
        "denied",
        "requires_decision",
        "skipped",
        "unknown",
    }
)

RUNTIME_EVENT_ACTORS = frozenset(
    {
        "runtime_runner",
        "model_adapter",
        "agent_flow",
        "tool_runtime",
        "permission_policy",
        "projection_manager",
        "headless_lab",
    }
)


class RuntimeEventValidationError(ValueError):
    """Raised when new RuntimeEvent v2 writes violate the envelope contract."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _new_event_id():
    return f"evt_{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class RuntimeEventV2:
    schema_version: int
    event_id: str
    invocation_id: str
    sequence: int
    kind: str
    status: str
    actor: str
    created_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    parent_event_id: str = ""
    correlation_id: str = ""

    @property
    def type(self) -> str:
        """Compatibility alias for legacy projection code during migration."""
        return self.kind


class RuntimeEventLedgerV2:
    """Append-only RuntimeEvent v2 ledger.

    The ledger owns sequence assignment. Callers provide the fact they want to
    record, not its position in the invocation.
    """

    def __init__(self, invocation_id: str):
        self.invocation_id = str(invocation_id)
        if not self.invocation_id:
            raise RuntimeEventValidationError("invocation_id is required")
        self._events: list[RuntimeEventV2] = []

    def append(
        self,
        kind: str,
        *,
        status: str,
        actor: str,
        payload: Mapping[str, Any] | None = None,
        parent_event_id: str = "",
        correlation_id: str = "",
    ) -> RuntimeEventV2:
        event = RuntimeEventV2(
            schema_version=RUNTIME_EVENT_SCHEMA_VERSION,
            event_id=_new_event_id(),
            invocation_id=self.invocation_id,
            sequence=len(self._events) + 1,
            kind=str(kind),
            status=str(status),
            actor=str(actor),
            created_at=_now(),
            payload=dict(payload or {}),
            parent_event_id=str(parent_event_id or ""),
            correlation_id=str(correlation_id or ""),
        )
        assert_valid_runtime_event_v2(event)
        self._events.append(event)
        return event

    @property
    def events(self) -> list[RuntimeEventV2]:
        return list(self._events)


def runtime_event_v2_to_dict(event: RuntimeEventV2) -> dict[str, Any]:
    assert_valid_runtime_event_v2(event)
    payload: dict[str, Any] = {
        "schema_version": event.schema_version,
        "event_id": event.event_id,
        "invocation_id": event.invocation_id,
        "sequence": event.sequence,
        "kind": event.kind,
        "status": event.status,
        "actor": event.actor,
        "created_at": event.created_at,
        "payload": dict(event.payload),
    }
    if event.parent_event_id:
        payload["parent_event_id"] = event.parent_event_id
    if event.correlation_id:
        payload["correlation_id"] = event.correlation_id
    return payload


def runtime_event_v2_from_dict(payload: Mapping[str, Any]) -> RuntimeEventV2:
    event = _event_v2_from_mapping(payload)
    assert_valid_runtime_event_v2(event)
    return event


def is_runtime_event_v2(value: Any) -> bool:
    if isinstance(value, RuntimeEventV2):
        return True
    if isinstance(value, Mapping):
        return value.get("schema_version") == RUNTIME_EVENT_SCHEMA_VERSION
    return getattr(value, "schema_version", None) == RUNTIME_EVENT_SCHEMA_VERSION


def validate_runtime_event_v2(event: RuntimeEventV2) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    if event.schema_version != RUNTIME_EVENT_SCHEMA_VERSION:
        diagnostics.append(_diagnostic("invalid_schema_version", "RuntimeEvent schema_version must be 2"))
    if not event.event_id:
        diagnostics.append(_diagnostic("missing_event_id", "RuntimeEvent v2 is missing event_id"))
    if not event.invocation_id:
        diagnostics.append(_diagnostic("missing_invocation_id", "RuntimeEvent v2 is missing invocation_id"))
    if not isinstance(event.sequence, int) or event.sequence < 1:
        diagnostics.append(_diagnostic("invalid_sequence", "RuntimeEvent v2 sequence must be a positive integer"))
    if not event.kind:
        diagnostics.append(_diagnostic("missing_kind", "RuntimeEvent v2 is missing kind"))
    elif event.kind not in RUNTIME_EVENT_KINDS:
        diagnostics.append(_diagnostic("unknown_kind", "RuntimeEvent v2 kind is not in the controlled vocabulary"))
    if not event.status:
        diagnostics.append(_diagnostic("missing_status", "RuntimeEvent v2 is missing status"))
    elif event.status not in RUNTIME_EVENT_STATUSES:
        diagnostics.append(_diagnostic("unknown_status", "RuntimeEvent v2 status is not in the controlled vocabulary"))
    if not event.actor:
        diagnostics.append(_diagnostic("missing_actor", "RuntimeEvent v2 is missing actor"))
    elif event.actor not in RUNTIME_EVENT_ACTORS:
        diagnostics.append(_diagnostic("unknown_actor", "RuntimeEvent v2 actor is not in the controlled vocabulary"))
    if not event.created_at:
        diagnostics.append(_diagnostic("missing_created_at", "RuntimeEvent v2 is missing created_at"))
    if not isinstance(event.payload, dict):
        diagnostics.append(_diagnostic("invalid_payload", "RuntimeEvent v2 payload must be an object"))
    if event.kind == "terminal_status" and event.status not in {"completed", "failed", "unknown"}:
        diagnostics.append(
            _diagnostic("invalid_terminal_status", "terminal_status must close the invocation with a run status")
        )
    return diagnostics


def assert_valid_runtime_event_v2(event: RuntimeEventV2) -> None:
    diagnostics = validate_runtime_event_v2(event)
    if diagnostics:
        codes = ", ".join(item["code"] for item in diagnostics)
        raise RuntimeEventValidationError(f"invalid RuntimeEvent v2 envelope: {codes}")


def normalize_runtime_event(event: Any, *, event_index: int = 0) -> tuple[RuntimeEventV2 | None, list[dict[str, Any]]]:
    """Normalize v2 or legacy runtime events into a v2 read shape.

    New writes should use RuntimeEventLedgerV2. This adapter exists for reading
    historical artifacts and for transitional projection code.
    """

    diagnostics: list[dict[str, Any]] = []
    if is_runtime_event_v2(event):
        try:
            normalized = event if isinstance(event, RuntimeEventV2) else _event_v2_from_mapping(_event_mapping(event))
        except Exception as exc:
            return None, [_diagnostic("unsupported_event_shape", f"invalid RuntimeEvent v2 shape: {exc}")]
        diagnostics.extend(validate_runtime_event_v2(normalized))
        return normalized, diagnostics

    mapping = _event_mapping(event)
    kind = _field(mapping, event, "type", "")
    raw_payload = _field(mapping, event, "payload", {})
    created_at = _field(mapping, event, "created_at", "")
    if not kind:
        return None, [
            _diagnostic(
                "unsupported_event_shape",
                "legacy runtime event is missing type",
                event_index=event_index,
            )
        ]
    if not isinstance(raw_payload, Mapping):
        return None, [
            _diagnostic(
                "unsupported_event_shape",
                "legacy runtime event payload is not an object",
                event_index=event_index,
                event_type=str(kind),
            )
        ]

    payload = dict(raw_payload)
    diagnostics.append(
        _diagnostic(
            "legacy_event_shape",
            "legacy runtime event was adapted to RuntimeEvent v2 read shape",
            event_index=event_index,
            event_type=str(kind),
        )
    )
    if not created_at:
        diagnostics.append(
            _diagnostic(
                "incomplete_event_shape",
                "legacy runtime event has no created_at timestamp",
                event_index=event_index,
                event_type=str(kind),
            )
        )
    invocation_id = str(payload.get("invocation_id") or "")
    if not invocation_id:
        diagnostics.append(
            _diagnostic(
                "missing_invocation_id",
                "legacy runtime event has no invocation_id",
                event_index=event_index,
                event_type=str(kind),
            )
        )
        invocation_id = "legacy_unknown_invocation"
    status = _infer_legacy_status(str(kind), payload)
    actor = _infer_legacy_actor(str(kind))
    normalized = RuntimeEventV2(
        schema_version=RUNTIME_EVENT_SCHEMA_VERSION,
        event_id=str(payload.get("event_id") or f"legacy_evt_{event_index + 1}"),
        invocation_id=invocation_id,
        sequence=event_index + 1,
        kind=str(kind),
        status=status,
        actor=actor,
        created_at=str(created_at or ""),
        payload=payload,
        parent_event_id=str(payload.get("parent_event_id") or ""),
        correlation_id=str(payload.get("correlation_id") or payload.get("tool_call_id") or payload.get("model_call_id") or ""),
    )
    diagnostics.extend(
        item
        for item in validate_runtime_event_v2(normalized)
        if item["code"] in {"unknown_kind", "unknown_status", "unknown_actor", "missing_created_at"}
    )
    return normalized, diagnostics


def normalize_runtime_events(events: Any) -> tuple[list[RuntimeEventV2], list[dict[str, Any]]]:
    normalized: list[RuntimeEventV2] = []
    diagnostics: list[dict[str, Any]] = []
    for index, event in enumerate(events or ()):
        normalized_event, event_diagnostics = normalize_runtime_event(event, event_index=index)
        diagnostics.extend(event_diagnostics)
        if normalized_event is not None:
            normalized.append(normalized_event)
    return normalized, diagnostics


def _event_v2_from_mapping(payload: Mapping[str, Any]) -> RuntimeEventV2:
    raw_payload = payload.get("payload", {})
    return RuntimeEventV2(
        schema_version=int(payload.get("schema_version", 0) or 0),
        event_id=str(payload.get("event_id", "")),
        invocation_id=str(payload.get("invocation_id", "")),
        sequence=int(payload.get("sequence", 0) or 0),
        kind=str(payload.get("kind", "")),
        status=str(payload.get("status", "")),
        actor=str(payload.get("actor", "")),
        created_at=str(payload.get("created_at", "")),
        payload=dict(raw_payload if isinstance(raw_payload, Mapping) else {}),
        parent_event_id=str(payload.get("parent_event_id", "")),
        correlation_id=str(payload.get("correlation_id", "")),
    )


def _event_mapping(event: Any) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return event
    return {}


def _field(mapping: Mapping[str, Any], event: Any, name: str, default: Any) -> Any:
    if name in mapping:
        return mapping.get(name, default)
    return getattr(event, name, default)


def _infer_legacy_status(kind: str, payload: Mapping[str, Any]) -> str:
    if kind == "invocation_start":
        return "started"
    if kind in {"model_output", "final_answer"}:
        return "completed"
    if kind in {"tool_argument_validation", "tool_result", "terminal_status"}:
        status = str(payload.get("status") or "unknown")
        return status if status in RUNTIME_EVENT_STATUSES else "unknown"
    if kind == "tool_permission_decision":
        decision = str(payload.get("decision") or "")
        if decision in {"denied", "requires_decision"}:
            return decision
        if decision == "deny":
            return "denied"
        if decision in {"allow", "allowed"}:
            return "ok"
        return "unknown"
    if kind == "tool_call_requested":
        return "started"
    return "unknown"


def _infer_legacy_actor(kind: str) -> str:
    if kind in {"model_output", "model_failure"}:
        return "model_adapter"
    if kind.startswith("tool_"):
        if kind == "tool_permission_decision":
            return "permission_policy"
        return "tool_runtime"
    if kind in {"final_answer"}:
        return "agent_flow"
    return "runtime_runner"


def _diagnostic(code: str, message: str, **details: Any) -> dict[str, Any]:
    diagnostic = {
        "code": code,
        "severity": "warning",
        "message": message,
    }
    diagnostic.update(details)
    return diagnostic
