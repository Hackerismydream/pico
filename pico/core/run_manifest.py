"""Runtime run manifest helpers."""

from __future__ import annotations

import subprocess

from .workspace import now

RUN_MANIFEST_SCHEMA_VERSION = 1


def build_run_manifest(runtime, task_state):
    sandbox = getattr(runtime, "sandbox_config", None)
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "created_at": now(),
        "run_id": task_state.run_id,
        "task_id": task_state.task_id,
        "session_id": runtime.session.get("id", ""),
        "workspace_root": str(runtime.root),
        "repo_commit": _git_value(runtime.root, ["rev-parse", "HEAD"]),
        "branch": _git_value(runtime.root, ["branch", "--show-current"]),
        "dirty": bool(_git_value(runtime.root, ["status", "--short"])),
        "model": str(getattr(runtime.model_client, "model", "")),
        "model_client": runtime.model_client.__class__.__name__,
        "approval_policy": runtime.approval_policy,
        "runtime_mode": runtime.runtime_mode,
        "read_only": bool(runtime.read_only),
        "max_steps": int(runtime.max_steps),
        "max_new_tokens": int(runtime.max_new_tokens),
        "feature_flags": dict(runtime.feature_flags),
        "sandbox": {
            "mode": str(getattr(sandbox, "mode", "")),
            "backend": str(getattr(sandbox, "backend", "")),
            "workspace_write": bool(getattr(sandbox, "workspace_write", False)),
        },
        "status": task_state.status,
        "stop_reason": task_state.stop_reason,
        "paths": {
            "task_state": "task_state.json",
            "trace": "trace.jsonl",
            "report": "report.json",
            "artifacts": "artifacts",
        },
    }


def _git_value(root, args):
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return completed.stdout.strip()
    except Exception:
        return ""
