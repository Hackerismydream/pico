"""Tool protocol objects for Pico.

Each tool owns its schema, policy, validation, activity text, and execution
function. The registry only collects these specs and adapts them to the runtime
map consumed by `Pico.run_tool()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from typing import Callable


ValidateFn = Callable[[object, dict], None]
RunFn = Callable[[object, dict], str]
ActivityFn = Callable[[dict], str]


class Effect(StrEnum):
    WORKSPACE_READ = "workspace_read"
    WORKSPACE_WRITE = "workspace_write"
    RUNTIME_STATE_READ = "runtime_state_read"
    RUNTIME_STATE_WRITE = "runtime_state_write"
    PROCESS_READ = "process_read"
    PROCESS_EXEC = "process_exec"
    ARTIFACT_WRITE = "artifact_write"
    USER_INTERACTION = "user_interaction"


@dataclass(frozen=True)
class ToolPolicy:
    read_only: bool = False
    concurrency: str = "serial"
    requires_prior_read: bool = False
    records_read: bool = False
    max_result_chars: int = 4000
    effects: tuple[Effect | str, ...] = ()

    def to_dict(self) -> dict:
        effects = [str(effect) for effect in self.effects]
        if not effects:
            effects = [str(Effect.WORKSPACE_READ if self.read_only else Effect.WORKSPACE_WRITE)]
        return {
            "read_only": bool(self.read_only),
            "concurrency": str(self.concurrency or "serial"),
            "requires_prior_read": bool(self.requires_prior_read),
            "records_read": bool(self.records_read),
            "max_result_chars": int(self.max_result_chars),
            "effects": effects,
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
