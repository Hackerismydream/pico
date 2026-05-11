"""Internal run-domain events.

These events drive state transitions. They are intentionally separate from
trace/session envelopes, which are audit outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunEvent:
    type: str
    payload: dict = field(default_factory=dict)
