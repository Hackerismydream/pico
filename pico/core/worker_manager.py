"""Session-scoped worker lifecycle for subagents."""

import json
import time
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .workspace import clip, now


@dataclass
class WorkerTask:
    id: str
    description: str
    subagent_type: str
    write_scope: tuple[str, ...]
    runtime: object


class WorkerManager:
    def __init__(self, runtime):
        self.runtime = runtime
        self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})
        self._tasks = {}

    @property
    def state(self):
        return self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})

    def spawn(self, description, prompt, subagent_type="worker", write_scope=None):
        subagent_type = _clean_type(subagent_type)
        if self.runtime.runtime_mode == "plan" and subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        task = self._new_task(description, subagent_type, write_scope)
        self._tasks[task.id] = task
        self._run(task, prompt, action="spawn")
        return self._public_payload(task)

    def continue_task(self, task_id, message):
        task = self._get_active_task(task_id)
        if self.runtime.runtime_mode == "plan" and task.subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        self._run(task, message, action="continue")
        return self._public_payload(task)

    def stop_task(self, task_id):
        item = self._get_item(task_id)
        if item["status"] == "running":
            item["status"] = "stopped"
            item["updated_at"] = now()
            self.runtime.session_event_bus.emit("worker_stopped", {"worker_id": item["id"], "status": "stopped"})
            self._save()
        return {"task_id": item["id"], "status": item["status"], "description": item["description"]}

    def to_dict(self):
        return {
            "next_id": int(self.state.get("next_id", 1)),
            "items": [dict(item) for item in self.state.get("items", [])],
        }

    def _new_task(self, description, subagent_type, write_scope):
        worker_id = f"agent_{int(self.state.get('next_id', 1))}"
        self.state["next_id"] = int(self.state.get("next_id", 1)) + 1
        scope = tuple(_clean_scope(write_scope))
        child = self._build_child(subagent_type, scope)
        item = {
            "id": worker_id,
            "description": str(description or "").strip() or "Worker task",
            "subagent_type": subagent_type,
            "write_scope": list(scope),
            "status": "idle",
            "result": "",
            "tool_steps": 0,
            "attempts": 0,
            "created_at": now(),
            "updated_at": now(),
        }
        self.state.setdefault("items", []).append(item)
        self._save()
        return WorkerTask(worker_id, item["description"], subagent_type, scope, child)

    def _build_child(self, subagent_type, write_scope):
        from .runtime import Pico

        child = Pico(
            model_client=self.runtime.model_client,
            workspace=self.runtime.workspace,
            session_store=self.runtime.session_store,
            run_store=self.runtime.run_store,
            approval_policy="never" if subagent_type == "Explore" else "auto",
            max_steps=self.runtime.max_steps,
            max_new_tokens=self.runtime.max_new_tokens,
            depth=self.runtime.depth + 1,
            max_depth=self.runtime.max_depth,
            read_only=subagent_type == "Explore" or (subagent_type == "worker" and not write_scope),
            secret_env_names=self.runtime.secret_env_names,
            shell_env_allowlist=self.runtime.shell_env_allowlist,
            feature_flags=self.runtime.feature_flags,
            write_scope=write_scope,
        )
        child.set_tool_profile("readonly" if subagent_type == "Explore" else "worker")
        child.refresh_prefix(force=True)
        return child

    def _run(self, task, prompt, action):
        item = self._get_item(task.id)
        item["status"] = "running"
        item["updated_at"] = now()
        self.runtime.session_event_bus.emit(
            "worker_started",
            {"worker_id": task.id, "description": task.description, "subagent_type": task.subagent_type, "action": action},
        )
        self._save()
        started = time.monotonic()
        try:
            result = task.runtime.ask(str(prompt or ""))
            status = "completed"
        except Exception as exc:
            result = f"error: worker failed: {exc}"
            status = "failed"
        task_state = getattr(task.runtime, "current_task_state", None)
        item.update(
            {
                "status": status,
                "result": clip(result, 2000),
                "tool_steps": int(getattr(task_state, "tool_steps", 0) or 0),
                "attempts": int(getattr(task_state, "attempts", 0) or 0),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "updated_at": now(),
            }
        )
        notification = self._notification(item)
        self.runtime.record({"role": "user", "content": notification, "created_at": now()})
        self.runtime.session_event_bus.emit(
            "worker_finished",
            {"worker_id": task.id, "status": status, "duration_ms": item["duration_ms"]},
        )
        self._save()

    def _notification(self, item):
        result = str(item.get("result", ""))
        parts = [
            "<task-notification>",
            f"<task-id>{escape(item['id'])}</task-id>",
            f"<status>{escape(item['status'])}</status>",
            f"<summary>{escape('Agent ' + item['description'] + ' ' + item['status'])}</summary>",
        ]
        if result:
            parts.append(f"<result>{escape(result)}</result>")
        parts.extend(
            [
                "<usage>",
                f"  <tool_uses>{int(item.get('tool_steps', 0))}</tool_uses>",
                f"  <attempts>{int(item.get('attempts', 0))}</attempts>",
                f"  <duration_ms>{int(item.get('duration_ms', 0))}</duration_ms>",
                "</usage>",
                "</task-notification>",
            ]
        )
        return "\n".join(parts)

    def _get_active_task(self, task_id):
        task = self._tasks.get(str(task_id))
        if task is None:
            raise ValueError(f"unknown or inactive worker: {task_id}")
        return task

    def _get_item(self, task_id):
        for item in self.state.setdefault("items", []):
            if item.get("id") == str(task_id):
                return item
        raise ValueError(f"unknown worker: {task_id}")

    def _public_payload(self, task):
        item = self._get_item(task.id)
        return {"task_id": task.id, "status": item["status"], "description": task.description}

    def _save(self):
        self.runtime.session_path = self.runtime.session_store.save(self.runtime.session)


def _clean_type(value):
    subagent_type = str(value or "worker").strip()
    if subagent_type not in {"worker", "Explore"}:
        raise ValueError("subagent_type must be worker or Explore")
    return subagent_type


def _clean_scope(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("write_scope must be a list of workspace paths")
    return [str(item).strip() for item in value if str(item).strip()]


def dumps_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
