"""Verification evidence extracted from tool execution trace events."""

VERIFY_MARKERS = (
    "pytest",
    "ruff",
    "mypy",
    "pyright",
    "compileall",
    "npm test",
    "npm run build",
    "pnpm test",
    "pnpm build",
)


def reduce_verification_signal(previous, event, changed_paths):
    signal = dict(previous or {})
    if event.get("event") != "tool_executed":
        return signal
    if event.get("workspace_changed"):
        signal = {
            "state": "missing",
            "last_workspace_change_span_id": str(event.get("span_id", "")),
            "changed_paths": list(changed_paths or []),
        }
    command = str((event.get("args", {}) or {}).get("command", "")).strip()
    if event.get("name") != "run_shell" or not _is_verification_command(command):
        return signal
    passed = str(event.get("status", "")) in {"", "ok"}
    signal.update(
        {
            "state": "passed" if passed else "failed",
            "source_span_id": str(event.get("span_id", "")),
            "command": command,
            "covers_changed_paths": bool(changed_paths),
            "changed_paths": list(changed_paths or []),
        }
    )
    return signal


def _is_verification_command(command):
    lowered = command.lower()
    return any(marker in lowered for marker in VERIFY_MARKERS)
