"""Read-only runtime snapshot for UI and other consumers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeSnapshot:
    model_name: str = ""
    approval_policy: str = ""
    session_id: str = ""
    cwd: str = ""
    runtime_mode: str = "execute"
    stage: str = ""
    tasks: list = field(default_factory=list)
    verification_status: str = "not_run"
    completion_gate: dict = field(default_factory=dict)
    subagent_count: int = 0
