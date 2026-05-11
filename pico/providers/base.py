"""Shared provider protocol values."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompletionResult:
    text: str
    metadata: dict = field(default_factory=dict)
