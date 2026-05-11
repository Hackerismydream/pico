"""Plan-mode state helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..core.workspace import now

RUNTIME_MODE_EXECUTE = "execute"
RUNTIME_MODE_PLAN = "plan"


@dataclass
class PlanModeController:
    root: Path

    def ensure_shape(self, session: dict) -> dict:
        runtime_mode = session.setdefault("runtime_mode", {})
        if not isinstance(runtime_mode, dict):
            runtime_mode = {}
            session["runtime_mode"] = runtime_mode
        runtime_mode.setdefault("mode", RUNTIME_MODE_EXECUTE)
        runtime_mode.setdefault("plan_file", "")
        runtime_mode.setdefault("topic", "")
        runtime_mode.setdefault("entered_at", "")
        return runtime_mode

    def mode(self, session: dict) -> str:
        runtime_mode = self.ensure_shape(session)
        mode = str(runtime_mode.get("mode", RUNTIME_MODE_EXECUTE))
        return mode if mode in {RUNTIME_MODE_EXECUTE, RUNTIME_MODE_PLAN} else RUNTIME_MODE_EXECUTE

    def plans_dir(self) -> Path:
        path = self.root / ".pico" / "plans"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def active_plan_path(self, session: dict, path_resolver) -> Path | None:
        runtime_mode = self.ensure_shape(session)
        plan_file = str(runtime_mode.get("plan_file", "")).strip()
        if not plan_file:
            return None
        return path_resolver(plan_file)

    def active_plan_relpath(self, session: dict, path_resolver) -> str:
        plan_path = self.active_plan_path(session, path_resolver)
        if plan_path is None:
            return ""
        return plan_path.relative_to(self.root).as_posix()

    def active_plan_has_content(self, session: dict, path_resolver) -> bool:
        plan_path = self.active_plan_path(session, path_resolver)
        if plan_path is None or not plan_path.exists():
            return False
        try:
            return bool(plan_path.read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            return False

    def enter(self, session: dict, topic="") -> Path:
        topic = str(topic or "").strip()
        plan_path = self.plans_dir() / f"plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}.md"
        plan_path.touch()
        session["runtime_mode"] = {
            "mode": RUNTIME_MODE_PLAN,
            "plan_file": plan_path.relative_to(self.root).as_posix(),
            "topic": topic,
            "entered_at": now(),
        }
        return plan_path

    def exit(self, session: dict, path_resolver) -> tuple[str, str]:
        plan_path = self.active_plan_path(session, path_resolver)
        plan_text = ""
        if plan_path is not None and plan_path.exists():
            plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
        previous_plan = self.active_plan_relpath(session, path_resolver)
        session["runtime_mode"] = {
            "mode": RUNTIME_MODE_EXECUTE,
            "plan_file": "",
            "topic": "",
            "entered_at": "",
        }
        return plan_text, previous_plan

    def prompt_section(self, session: dict, path_resolver) -> str:
        if self.mode(session) != RUNTIME_MODE_PLAN:
            return ""
        plan_relpath = self.active_plan_relpath(session, path_resolver)
        topic = str(session["runtime_mode"].get("topic", "")).strip()
        lines = [
            "Runtime mode: plan",
            f"- Active plan file: {plan_relpath}",
            "- Allowed actions: list_files, read_file, glob, grep, search, delegate, and writes to the active plan file only.",
            "- Do not edit project files until the plan is approved and runtime mode returns to execute.",
        ]
        if topic:
            lines.append(f"- Planning topic: {topic}")
        return "\n".join(lines)
