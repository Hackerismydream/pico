"""Verification evidence extracted from tool execution trace events."""

import shlex


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
    command_class = classify_verification_command(command)
    if event.get("name") != "run_shell" or not command_class:
        return signal
    passed = str(event.get("status", "")) in {"", "ok"}
    signal.update(
        {
            "state": "passed" if passed else "failed",
            "source_span_id": str(event.get("span_id", "")),
            "command": command,
            "command_class": command_class,
            "after_last_workspace_change": bool(
                signal.get("last_workspace_change_span_id") or changed_paths
            ),
            "changed_paths_present": bool(changed_paths),
            "covers_changed_paths": False,
            "coverage_confidence": "unknown",
            "changed_paths": list(changed_paths or []),
        }
    )
    return signal


def classify_verification_command(command):
    try:
        tokens = shlex.split(str(command))
    except ValueError:
        tokens = str(command).split()
    tokens = [token.lower() for token in tokens]
    if not tokens or tokens[0] in {"echo", "printf", "grep", "rg", "cat"}:
        return ""
    if tokens[0] == "uv" and len(tokens) > 2 and tokens[1] == "run":
        while len(tokens) > 2 and tokens[2].startswith("-"):
            tokens = tokens[:2] + tokens[3:]
        tokens = tokens[2:]
    python_cmd = tokens[0].rsplit("/", 1)[-1]
    if len(tokens) > 2 and python_cmd in {"python", "python3"} and tokens[1] == "-m":
        return {"pytest": "test", "compileall": "compile"}.get(tokens[2], "")
    if tokens[0] in {"pytest", "tox"}:
        return "test"
    if tokens[0] == "ruff" and len(tokens) > 1 and tokens[1] == "check":
        return "lint"
    if tokens[0] in {"mypy", "pyright"}:
        return "typecheck"
    if tokens[0] in {"npm", "pnpm"}:
        return _js_command_class(tokens)
    if tokens[:2] in (["yarn", "test"], ["go", "test"], ["cargo", "test"], ["make", "test"]):
        return "test"
    return ""


def _js_command_class(tokens):
    if len(tokens) < 2:
        return ""
    if tokens[1] == "test":
        return "test"
    if len(tokens) > 2 and tokens[1] == "run" and tokens[2] in {"test", "build"}:
        return "test" if tokens[2] == "test" else "build"
    if tokens[1] == "build":
        return "build"
    return ""
