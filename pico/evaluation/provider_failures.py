"""PicoBench provider 失败分类辅助函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def provider_error_from_evidence(evidence_path: str | Path | None) -> dict[str, Any]:
    """从 evidence bundle 的 trace.jsonl 中读取最近一次 provider 错误。"""
    if not evidence_path:
        return {}
    trace_path = Path(evidence_path) / "trace.jsonl"
    if not trace_path.exists():
        return {}
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "model_error":
            continue
        error = event.get("error")
        if isinstance(error, dict):
            return error
        metadata = event.get("completion_metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("provider_error"), dict):
            return metadata["provider_error"]
    return {}


def provider_failure_category(provider_error: dict[str, Any]) -> str:
    """把 provider 原始错误归一成 PicoBench failure category。"""
    if not provider_error:
        return "model_error"
    status = provider_error.get("http_status")
    body = str(provider_error.get("body_excerpt") or "").lower()
    code = str(provider_error.get("code") or "").lower()
    cause_type = str(provider_error.get("cause_type") or "").lower()
    if status == 402 or "insufficient balance" in body or "insufficient_balance" in body:
        return "provider_insufficient_balance"
    if status in {401, 403} or "auth" in code or "auth" in body:
        return "provider_auth_error"
    if status == 429 or "rate" in code or "rate limit" in body:
        return "provider_rate_limited"
    if "network" in code or "incompleteread" in body or cause_type in {"urlerror", "timeouterror", "connectionerror", "incompleteread"}:
        return "provider_network_error"
    if isinstance(status, int) and status >= 500:
        return "provider_http_error"
    return "model_error"


def normalized_failure_category(result: dict[str, Any]) -> str:
    """对旧 summary 中的 model_error 做 evidence-based 重分类。"""
    category = str(result.get("failure_category") or "")
    if category != "model_error":
        return category
    return provider_failure_category(provider_error_from_evidence(result.get("evidence_path")))
