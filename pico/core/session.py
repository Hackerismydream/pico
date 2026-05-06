"""Session persistence for Pico runtime."""

import json
from datetime import datetime
from pathlib import Path

RUNTIME_MODE_EXECUTE = "execute"


class SessionStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id):
        return self.root / f"{session_id}.json"

    def event_path(self, session_id):
        return self.root / f"{session_id}.events.jsonl"

    def save(self, session):
        path = self.path(session["id"])
        path.write_text(json.dumps(session, indent=2), encoding="utf-8")
        return path

    def append_event(self, session_id, event):
        path = self.event_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
        return path

    def load(self, session_id):
        return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self):
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None

    def list_sessions(self):
        sessions = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            sessions.append(
                {
                    "id": path.stem,
                    "path": str(path),
                    "created_at": session.get("created_at", ""),
                    "history_count": len(session.get("history", []) or []),
                    "workspace_root": session.get("workspace_root", ""),
                    "runtime_mode": (session.get("runtime_mode") or {}).get("mode", RUNTIME_MODE_EXECUTE),
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                }
            )
        return sessions


__all__ = ["SessionStore"]
