"""Shell command guardrails for the local tool runtime."""

from __future__ import annotations

import re
import shlex

from ..core.workspace import MAX_TOOL_OUTPUT


COMMAND_SUBSTITUTION_PATTERNS = (
    (re.compile(r"<\("), "process substitution <()"),
    (re.compile(r">\("), "process substitution >()"),
    (re.compile(r"=\("), "zsh process substitution =()"),
    (re.compile(r"(?:^|[\s;&|])=[A-Za-z_]"), "zsh equals expansion (=cmd)"),
    (re.compile(r"\$\((?!\s*(?:pwd|dirname|basename)(?:\s|\)|$))[^)]+\)"), "$() command substitution"),
    (re.compile(r"`(?!\s*(?:pwd|dirname|basename)(?:\s|`|$))[^`]+`"), "backtick command substitution"),
)

SHELL_ESCAPE_PATTERNS = (
    (re.compile(r"\bzmodload\b"), "zsh module loading"),
    (re.compile(r"\bzpty\b"), "zsh pseudo-terminal"),
    (re.compile(r"\bsys(open|read|write)\b"), "zsh low-level file IO"),
    (re.compile(r"\bzf_(rm|mv)\b"), "zsh file module operation"),
)

DESTRUCTIVE_PATTERNS = (
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "may discard uncommitted changes"),
    (re.compile(r"\bgit\s+push\b[^;&|\n]*\s(--force|--force-with-lease|-f)\b"), "may overwrite remote history"),
    (
        re.compile(r"(^|[;&|\n]\s*)rm\s+-[A-Za-z]*[rR][A-Za-z]*f[A-Za-z]*\s+(/|/\*|~|\$HOME|\.{1,2})(\s|$|[;&|])"),
        "may recursively remove a high-impact path",
    ),
    (re.compile(r"\b(DROP|TRUNCATE)\s+(TABLE|DATABASE|SCHEMA)\b", re.I), "may destroy database objects"),
    (re.compile(r"\bDELETE\s+FROM\s+\w+\s*(;|$)", re.I), "may delete all rows from a database table"),
    (re.compile(r"\bkubectl\s+delete\b"), "may delete Kubernetes resources"),
    (re.compile(r"\bterraform\s+destroy\b"), "may destroy Terraform infrastructure"),
)

READ_ONLY_COMMANDS = {"pwd", "ls", "find", "rg", "grep", "cat", "head", "tail", "wc"}
READ_ONLY_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
READ_ONLY_SHELL_OPERATOR_PATTERN = re.compile(r"(\|\||&&|;|\||>|<|\n)")


def split_shell_segments(command: str) -> list[str]:
    """Split enough shell syntax to inspect simple leading commands."""
    return [segment.strip() for segment in re.split(r"\s*(?:&&|;|\|\|)\s*", str(command)) if segment.strip()]


def detect_blocked_sleep(command: str) -> str:
    segments = split_shell_segments(command)
    if not segments:
        return ""
    match = re.fullmatch(r"sleep\s+(\d+)", segments[0])
    if not match:
        return ""
    seconds = int(match.group(1))
    if seconds < 2:
        return ""
    if len(segments) == 1:
        return f"standalone sleep {seconds}"
    return f"sleep {seconds} before {segments[1]}"


def shell_command_block_reason(command: str) -> str:
    command = str(command)
    sleep_reason = detect_blocked_sleep(command)
    if sleep_reason:
        return f"{sleep_reason}; use a bounded command or polling check instead"

    for pattern, reason in (*COMMAND_SUBSTITUTION_PATTERNS, *SHELL_ESCAPE_PATTERNS, *DESTRUCTIVE_PATTERNS):
        if pattern.search(command):
            return reason
    return ""


def is_read_only_shell_command(command: str) -> bool:
    """Return whether a shell command is safe enough for read-only subagents."""
    command = str(command or "").strip()
    if not command:
        return False
    if shell_command_block_reason(command):
        return False
    if READ_ONLY_SHELL_OPERATOR_PATTERN.search(command):
        return False

    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    while parts and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parts[0]):
        parts.pop(0)
    if not parts:
        return False

    name = parts[0].rsplit("/", 1)[-1]
    if name == "git":
        return len(parts) >= 2 and parts[1] in READ_ONLY_GIT_SUBCOMMANDS
    if name == "sed":
        return len(parts) >= 2 and parts[1] == "-n"
    if name == "find":
        return not any(part in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for part in parts)
    return name in READ_ONLY_COMMANDS


def validate_shell_command(command: str) -> None:
    reason = shell_command_block_reason(command)
    if reason:
        raise ValueError(f"blocked shell command: {reason}")


def head_tail_clip(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    marker = "\n...[truncated middle]...\n"
    budget = max(0, limit - len(marker))
    head_chars = budget // 2
    tail_chars = budget - head_chars
    tail = text[-tail_chars:] if tail_chars else ""
    return text[:head_chars] + marker + tail


def format_shell_result(returncode: int, stdout: str, stderr: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    text = "\n".join(
        [
            f"exit_code: {int(returncode)}",
            "stdout:",
            str(stdout).strip() or "(empty)",
            "stderr:",
            str(stderr).strip() or "(empty)",
        ]
    )
    return head_tail_clip(text.strip(), limit=limit)
