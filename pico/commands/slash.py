from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from ..features.skills import parse_skill_command


@dataclass(frozen=True)
class SlashCommand:
    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("help", "/help", "Show TUI commands.", ("h",)),
    SlashCommand("clear", "/clear", "Clear the visible chat log."),
    SlashCommand("new", "/new", "Reset session history and memory."),
    SlashCommand("memory", "/memory", "Show working memory."),
    SlashCommand("session", "/session", "Show session and event paths."),
    SlashCommand("context", "/context", "Show the last context usage breakdown."),
    SlashCommand("trace", "/trace", "Show the latest run trace path."),
    SlashCommand("tasks", "/tasks", "Show the current task ledger."),
    SlashCommand("verify", "/verify", "Show recent verification artifacts."),
    SlashCommand("agents", "/agents", "Show subagent status and recent results.", ("agent",)),
    SlashCommand("subagent", "/subagent explore <task>", "Launch an Explore or Worker subagent.", ("sub",)),
    SlashCommand("skills", "/skills", "List available Pico skills.", ("sk",)),
    SlashCommand("skill", "/skill <name> [args]", "Load and run a Pico skill.", ()),
    SlashCommand("history", "/history", "List saved sessions for this workspace."),
    SlashCommand("resume", "/resume <id>", "Resume a saved session by id or prefix."),
    SlashCommand("compact", "/compact [n]", "Compact older history into a persisted summary."),
    SlashCommand("plan", "/plan [task]", "Enter plan mode, or plan the given task."),
    SlashCommand("execute", "/execute", "Exit plan mode and return to normal execution.", ("exit-plan",)),
    SlashCommand("approval", "/approval auto|ask|never", "Change approval policy for this session."),
)


def command_help_markdown() -> str:
    lines = ["# Pico TUI commands", "", "| Command | Description |", "| --- | --- |"]
    for command in SLASH_COMMANDS:
        lines.append(f"| `{command.usage}` | {command.description} |")
    return "\n".join(lines) + "\n"


def resolve_command(name: str) -> SlashCommand | None:
    normalized = str(name or "").strip().lstrip("/").lower()
    if not normalized:
        return None
    for command in SLASH_COMMANDS:
        if normalized == command.name or normalized in command.aliases:
            return command
    return None


def suggest_commands(text: str, limit: int = 8) -> list[SlashCommand]:
    raw = str(text or "")
    if not raw.startswith("/"):
        return []
    body = raw[1:]
    if " " in body:
        return []
    token = body.lower()
    matches = []
    for command in SLASH_COMMANDS:
        names = (command.name, *command.aliases)
        if not token or any(name.startswith(token) for name in names):
            matches.append(command)
    return matches[:limit]


def parse_subagent_args(args: str) -> tuple[dict | None, str]:
    usage = "Usage: `/subagent explore <task>` or `/subagent worker --scope <path[,path]> <task>`."
    try:
        tokens = shlex.split(str(args or ""))
    except ValueError as exc:
        return None, f"{usage} {exc}"
    if not tokens:
        return None, usage

    subagent_type = "Explore"
    if tokens[0].lower() in {"explore", "worker"}:
        subagent_type = "Worker" if tokens.pop(0).lower() == "worker" else "Explore"

    write_scope: list[str] = []
    task_parts: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--scope":
            index += 1
            if index >= len(tokens):
                return None, usage
            write_scope.extend(_split_scope(tokens[index]))
        elif token.startswith("--scope="):
            write_scope.extend(_split_scope(token.split("=", 1)[1]))
        else:
            task_parts.append(token)
        index += 1

    prompt = " ".join(task_parts).strip()
    if not prompt:
        return None, usage
    if subagent_type == "Worker" and not write_scope:
        return None, usage
    return {
        "description": prompt[:80],
        "prompt": prompt,
        "subagent_type": subagent_type,
        "write_scope": write_scope,
        "background": True,
    }, ""


def parse_skill_args(args: str) -> tuple[dict | None, str]:
    usage = "Usage: `/skill <name> [args]` or `/skill:<name> [args]`."
    raw = str(args or "").strip()
    command_text = f"/{raw}" if raw.startswith("skill:") else f"/skill {raw}"
    command = parse_skill_command(command_text)
    if command is None:
        return None, usage
    return {"name": command.name, "args": command.args}, ""


def _split_scope(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]
