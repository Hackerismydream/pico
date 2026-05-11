"""Per-run mutable control state.

`RunState` is the persisted snapshot. `RunContext` only carries loop budgets and
per-turn recovery counters while a single ask() turn is executing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunContext:
    task_state: object
    user_message: str
    max_steps: int
    max_attempts: int
    current_max_new_tokens: int
    truncation_recovery_count: int = 0
    model_error_recovery_count: int = 0
    user_recorded: bool = False

    @classmethod
    def create(cls, task_state, user_message: str, max_steps: int, max_new_tokens: int):
        max_steps = int(max_steps)
        return cls(
            task_state=task_state,
            user_message=str(user_message),
            max_steps=max_steps,
            max_attempts=max(max_steps * 3, max_steps + 4),
            current_max_new_tokens=int(max_new_tokens),
        )

    @property
    def attempts(self) -> int:
        return int(getattr(self.task_state, "attempts", 0))

    @property
    def tool_steps(self) -> int:
        return int(getattr(self.task_state, "tool_steps", 0))

    @property
    def remaining_tool_steps(self) -> int:
        return max(0, self.max_steps - self.tool_steps)

    def can_continue(self) -> bool:
        return self.tool_steps < self.max_steps and self.attempts < self.max_attempts

    def record_attempt(self):
        self.task_state.record_attempt()
        return self

    def record_tool(self, name: str):
        self.task_state.record_tool(name)
        return self
