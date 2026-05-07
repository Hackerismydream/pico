"""Tool protocol objects for Pico.

Each tool owns its schema, policy, validation, activity text, and execution
function. The registry only collects these specs and adapts them to the runtime
map consumed by `Pico.run_tool()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import Callable


ValidateFn = Callable[[object, dict], None]
RunFn = Callable[[object, dict], str]
ActivityFn = Callable[[dict], str]


@dataclass(frozen=True)
class ToolPolicy:
    read_only: bool = False
    concurrency: str = "serial"
    requires_prior_read: bool = False
    records_read: bool = False
    max_result_chars: int = 4000

    def to_dict(self) -> dict:
        return {
            "read_only": bool(self.read_only),
            "concurrency": str(self.concurrency or "serial"),
            "requires_prior_read": bool(self.requires_prior_read),
            "records_read": bool(self.records_read),
            "max_result_chars": int(self.max_result_chars),
        }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict
    description: str
    run: RunFn
    validate: ValidateFn | None = None
    activity: ActivityFn | None = None
    example: str = ""
    risky: bool = False
    policy: ToolPolicy = field(default_factory=ToolPolicy)

    @property
    def read_only(self) -> bool:
        return bool(self.policy.read_only)

    def activity_description(self, args: dict | None = None) -> str:
        if self.activity:
            return str(self.activity(args or {}))
        return f"Running {self.name}"

    def materialize(self, agent) -> dict:
        policy = self.policy.to_dict()
        return {
            "schema": dict(self.schema),
            "risky": bool(self.risky),
            "description": str(self.description),
            "example": str(self.example),
            "policy": policy,
            "read_only": bool(policy.get("read_only", not self.risky)),
            "activity": self.activity_description({}),
            "run": partial(self.run, agent),
        }

