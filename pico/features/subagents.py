"""Subagent lifecycle management for Pico.

Subagents are bounded child runs owned by the main Pico runtime. They report
back through structured notifications instead of directly mutating the parent
conversation.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Callable

from ..core.workspace import now


SUBAGENT_RUNNING = "running"
SUBAGENT_COMPLETED = "completed"
SUBAGENT_FAILED = "failed"
SUBAGENT_KILLED = "killed"


@dataclass
class SubagentUsage:
    tool_uses: int = 0
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "tool_uses": int(self.tool_uses),
            "duration_ms": int(self.duration_ms),
        }


@dataclass
class SubagentTask:
    task_id: str
    description: str
    subagent_type: str
    runner: Callable
    prompt: str = ""
    status: str = SUBAGENT_RUNNING
    result: str = ""
    error: str = ""
    run_id: str = ""
    write_scope: list[str] = field(default_factory=list)
    max_steps: int = 0
    usage: SubagentUsage = field(default_factory=SubagentUsage)
    thread: threading.Thread | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    state: dict = field(default_factory=dict)
    started_at: str = field(default_factory=now)
    finished_at: str = ""
    current_activity: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "subagent_type": self.subagent_type,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "run_id": self.run_id,
            "write_scope": list(self.write_scope),
            "max_steps": int(self.max_steps),
            "usage": self.usage.to_dict(),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "current_activity": self.current_activity,
        }


def normalize_subagent_type(value: str | None) -> str:
    raw = str(value or "Explore").strip() or "Explore"
    if raw.lower() == "worker":
        return "Worker"
    if raw.lower() == "explore":
        return "Explore"
    return raw


class SubagentManager:
    """Manage child agent tasks and their completion notifications."""

    def __init__(self, runners: dict[str, Callable]):
        self._runners = dict(runners)
        self._tasks: dict[str, SubagentTask] = {}
        self._lock = threading.Lock()
        self._notifications: Queue[dict] = Queue()

    def spawn(
        self,
        *,
        description: str,
        prompt: str,
        subagent_type: str = "Explore",
        write_scope: list[str] | None = None,
        max_steps: int | None = None,
        background: bool = True,
    ) -> dict:
        subagent_type = normalize_subagent_type(subagent_type)
        runner = self._runners.get(subagent_type)
        if runner is None:
            known = ", ".join(sorted(self._runners))
            raise ValueError(f"unknown subagent_type: {subagent_type}; available: {known}")
        if subagent_type == "Worker" and not write_scope:
            raise ValueError("write_scope is required for Worker subagents")

        task = SubagentTask(
            task_id=f"agent-{uuid.uuid4().hex[:8]}",
            description=str(description or "").strip() or "Subagent task",
            subagent_type=subagent_type,
            runner=runner,
            prompt=str(prompt or ""),
            write_scope=[str(item) for item in (write_scope or [])],
            max_steps=int(max_steps or 0),
        )
        with self._lock:
            self._tasks[task.task_id] = task

        if background:
            task.thread = threading.Thread(
                target=self._run_task,
                name=task.task_id,
                args=(task, task.prompt),
                daemon=True,
            )
            task.thread.start()
            return {
                "task_id": task.task_id,
                "status": "started",
                "description": task.description,
                "subagent_type": task.subagent_type,
            }

        self._run_task(task, task.prompt, enqueue=False)
        return self._notification_payload(task)

    def continue_task(self, *, task_id: str, message: str, background: bool = True) -> dict:
        task = self._get_task(task_id)
        if self._is_running(task):
            raise ValueError("task is still running")
        task.cancel_event = threading.Event()
        task.status = SUBAGENT_RUNNING
        task.prompt = str(message or "")
        task.result = ""
        task.error = ""
        task.finished_at = ""
        if background:
            task.thread = threading.Thread(
                target=self._run_task,
                name=task.task_id,
                args=(task, task.prompt),
                daemon=True,
            )
            task.thread.start()
            return {
                "task_id": task.task_id,
                "status": "started",
                "description": task.description,
                "subagent_type": task.subagent_type,
            }
        self._run_task(task, task.prompt, enqueue=False)
        return self._notification_payload(task)

    def stop_task(self, task_id: str) -> dict:
        task = self._get_task(task_id)
        if not self._is_running(task):
            return {
                "task_id": task.task_id,
                "status": task.status,
                "description": task.description,
                "subagent_type": task.subagent_type,
            }
        task.cancel_event.set()
        task.status = "stopping"
        return {
            "task_id": task.task_id,
            "status": "stopping",
            "description": task.description,
            "subagent_type": task.subagent_type,
        }

    def drain_notifications(self) -> list[dict]:
        drained = []
        while True:
            try:
                drained.append(self._notifications.get_nowait())
            except Empty:
                return drained

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [task.to_dict() for task in self._tasks.values()]

    def running_status(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": task.task_id,
                    "description": task.description,
                    "subagent_type": task.subagent_type,
                    "status": task.status,
                    "tool_uses": task.usage.tool_uses,
                    "activity": task.current_activity,
                }
                for task in self._tasks.values()
                if self._is_running(task)
            ]

    def _get_task(self, task_id: str) -> SubagentTask:
        with self._lock:
            task = self._tasks.get(str(task_id))
        if task is None:
            raise ValueError(f"unknown task_id: {task_id}")
        return task

    @staticmethod
    def _is_running(task: SubagentTask) -> bool:
        return task.thread is not None and task.thread.is_alive()

    def _run_task(self, task: SubagentTask, prompt: str, enqueue: bool = True) -> None:
        started = time.monotonic()
        task.current_activity = "running"
        try:
            result = task.runner(task, prompt, task.cancel_event)
            result = dict(result or {})
            task.status = str(result.get("status") or SUBAGENT_COMPLETED)
            task.result = str(result.get("result") or "")
            task.error = str(result.get("error") or "")
            task.run_id = str(result.get("run_id") or task.run_id)
            task.usage.tool_uses = int(result.get("tool_uses") or 0)
            if task.cancel_event.is_set() and task.status == SUBAGENT_RUNNING:
                task.status = SUBAGENT_KILLED
        except Exception as exc:
            task.status = SUBAGENT_FAILED
            task.error = str(exc)
            task.result = str(exc)
        finally:
            task.current_activity = ""
            task.finished_at = now()
            task.usage.duration_ms = int((time.monotonic() - started) * 1000)
            if enqueue:
                self._notifications.put(self._notification_payload(task))

    def _notification_payload(self, task: SubagentTask) -> dict:
        payload = task.to_dict()
        payload["usage"] = task.usage.to_dict()
        return payload
