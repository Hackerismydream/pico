"""Provider metadata normalization for Pico runtimes."""

from __future__ import annotations


TRUNCATED_REASONS = {"length", "max_tokens", "max_output_tokens", "output_truncated"}


def normalize_completion_metadata(metadata: dict | None, transport: str = "") -> dict:
    normalized = dict(metadata or {})
    finish_reason = str(normalized.get("finish_reason") or normalized.get("stop_reason") or "unknown")
    stop_reason = str(normalized.get("stop_reason") or finish_reason)
    normalized["finish_reason"] = finish_reason
    normalized["stop_reason"] = stop_reason
    if transport:
        normalized["provider_transport"] = transport
    else:
        normalized.setdefault("provider_transport", str(normalized.get("transport", "")))
    normalized.setdefault("input_tokens", int(normalized.get("input_tokens", 0) or 0))
    normalized.setdefault("output_tokens", int(normalized.get("output_tokens", 0) or 0))
    return normalized


def is_truncated(metadata: dict | None) -> bool:
    normalized = normalize_completion_metadata(metadata)
    reason = str(normalized.get("finish_reason") or normalized.get("stop_reason") or "").lower()
    return reason in TRUNCATED_REASONS


def is_recoverable_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "could not extract text from response" in message
        or "could not extract text from event stream response" in message
        or "returned non-json content" in message
    )
