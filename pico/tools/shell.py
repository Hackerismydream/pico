"""Shell execution tool."""

from __future__ import annotations

import subprocess

from .shell_safety import format_shell_result, validate_shell_command
from .spec import ToolPolicy, ToolSpec


def validate_run_shell(agent, args):
    command = str(args.get("command", "")).strip()
    if not command:
        raise ValueError("command must not be empty")
    validate_shell_command(command)
    timeout = int(args.get("timeout", 20))
    if timeout < 1 or timeout > 120:
        raise ValueError("timeout must be in [1, 120]")


def tool_run_shell(agent, args):
    command = str(args.get("command", "")).strip()
    if not command:
        raise ValueError("command must not be empty")
    timeout = int(args.get("timeout", 20))
    if timeout < 1 or timeout > 120:
        raise ValueError("timeout must be in [1, 120]")
    result = subprocess.run(
        command,
        cwd=agent.root,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=agent.shell_env(),
    )
    return format_shell_result(result.returncode, result.stdout, result.stderr)


TOOL_SPECS = [
    ToolSpec(
        name="run_shell",
        schema={"command": "str", "timeout": "int=20"},
        description="Run a shell command in the repo root.",
        example='<tool>{"name":"run_shell","args":{"command":"uv run --with pytest python -m pytest -q","timeout":20}}</tool>',
        risky=True,
        policy=ToolPolicy(read_only=False, concurrency="serial"),
        activity=lambda args: "Running shell command",
        validate=validate_run_shell,
        run=tool_run_shell,
    )
]

