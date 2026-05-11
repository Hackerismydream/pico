"""Workspace and runtime-mode policy helpers for tools."""

from __future__ import annotations

import os

from ..features import memory as memorylib

RUNTIME_MODE_PLAN = "plan"


class ToolPolicyController:
    def tool_policy_state(self, host):
        host._ensure_session_shape()
        return host.session["tool_policy"]

    def read_ledger(self, host):
        return self.tool_policy_state(host).setdefault("read_ledger", {})

    def canonical_tool_path(self, host, args):
        raw_path = str((args or {}).get("path", "")).strip()
        if not raw_path:
            return ""
        return host.path(raw_path).relative_to(host.root).as_posix()

    def validate_prior_read_policy(self, host, name, args):
        tool = host.tools.get(name, {})
        policy = tool.get("policy", {})
        if not policy.get("requires_prior_read"):
            return
        canonical_path = self.canonical_tool_path(host, args)
        entry = self.read_ledger(host).get(canonical_path)
        if not entry:
            raise ValueError(f"{name} requires prior read_file for {canonical_path}")
        current = memorylib.file_freshness(canonical_path, host.root)
        if entry.get("freshness") != current:
            raise ValueError(f"{name} requires a fresh read_file for {canonical_path}")

    def validate_existing_write_read_policy(self, host, name, args):
        if name not in {"write_file", "write_files"}:
            return
        if name == "write_files":
            candidates = [
                str(item.get("path", "")).strip()
                for item in (args or {}).get("files", []) or []
                if isinstance(item, dict)
            ]
        else:
            candidates = [str((args or {}).get("path", "")).strip()]
        for raw_path in candidates:
            if not raw_path:
                continue
            target = host.path(raw_path)
            if not target.exists():
                continue
            canonical_path = target.relative_to(host.root).as_posix()
            entry = self.read_ledger(host).get(canonical_path)
            if not entry:
                raise ValueError(f"{name} requires prior read_file for {canonical_path}")
            current = memorylib.file_freshness(canonical_path, host.root)
            if entry.get("freshness") != current:
                raise ValueError(f"{name} requires a fresh read_file for {canonical_path}")

    def validate_write_scope_policy(self, host, name, args):
        if not host.write_scope or name not in {"write_file", "write_files", "patch_file"}:
            return
        raw_paths = _write_paths(name, args)
        allowed = []
        for scope in host.write_scope:
            try:
                allowed.append(host.path(scope))
            except Exception:
                continue
        if not allowed:
            raise ValueError("subagent write_scope is empty")
        for raw_path in raw_paths:
            if not raw_path:
                continue
            target = host.path(raw_path)
            if not any(os.path.commonpath([str(scope), str(target)]) == str(scope) for scope in allowed):
                relpath = target.relative_to(host.root).as_posix()
                scopes = ", ".join(path.relative_to(host.root).as_posix() for path in allowed)
                raise ValueError(f"{relpath} is outside subagent write_scope ({scopes})")

    def is_active_plan_file_write(self, host, name, args):
        if host.runtime_mode != RUNTIME_MODE_PLAN or name not in {"write_file", "patch_file"}:
            return False
        active = host.active_plan_path()
        if active is None:
            return False
        try:
            target = host.path((args or {}).get("path", ""))
        except Exception:
            return False
        return target == active

    def validate_runtime_mode_policy(self, host, name, args):
        if host.runtime_mode != RUNTIME_MODE_PLAN:
            return
        tool = host.tools.get(name, {})
        if bool(tool.get("read_only", not tool.get("risky", True))):
            return
        if self.is_active_plan_file_write(host, name, args):
            return
        plan_relpath = host.active_plan_relpath() or "(no active plan file)"
        raise ValueError(f"plan mode denied: {name} can only write the active plan file ({plan_relpath})")

    def update_tool_policy_after_tool(self, host, name, args, result, status):
        if status != "ok" or name != "read_file":
            return
        canonical_path = self.canonical_tool_path(host, args)
        if not canonical_path:
            return
        self.read_ledger(host)[canonical_path] = {
            "freshness": memorylib.file_freshness(canonical_path, host.root),
            "read_at": host.now_text(),
            "result_chars": len(str(result)),
        }
        host.session_path = host.session_store.save(host.session)


def _write_paths(name, args) -> list[str]:
    if name == "write_files":
        return [
            str(item.get("path", "")).strip()
            for item in (args or {}).get("files", []) or []
            if isinstance(item, dict)
        ]
    return [str((args or {}).get("path", "")).strip()]
