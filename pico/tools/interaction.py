"""User interaction tools."""

from __future__ import annotations

from .spec import ToolPolicy, ToolSpec


def validate_ask_user(agent, args):
    question = str(args.get("question", "")).strip()
    if not question:
        raise ValueError("question must not be empty")
    options = args.get("options", [])
    if options is None:
        options = []
    if not isinstance(options, list):
        raise ValueError("options must be a list")
    if len(options) > 5:
        raise ValueError("options must contain at most 5 entries")
    for index, item in enumerate(options, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"option {index} must be an object")
        if not str(item.get("label", "")).strip():
            raise ValueError(f"option {index} missing label")


def tool_ask_user(agent, args):
    question = str(args.get("question", "")).strip()
    if not question:
        raise ValueError("question must not be empty")
    lines = [
        "Clarification requested:",
        question,
        "",
        "Interactive user input is not available inside this tool call. Continue with the safest reasonable assumption, or return a concise final answer explaining the blocker if the ambiguity would change the requested outcome.",
    ]
    options = args.get("options") or []
    if options:
        lines.append("")
        lines.append("Options:")
        for item in options:
            label = str(item.get("label", "")).strip()
            description = str(item.get("description", "")).strip()
            lines.append(f"- {label}: {description}" if description else f"- {label}")
    return "\n".join(lines)


TOOL_SPECS = [
    ToolSpec(
        name="ask_user",
        schema={"question": "str", "options": "list[{label:str,description:str}]?"},
        description="Record a required clarification question when progress would otherwise contradict the user intent.",
        example='<tool>{"name":"ask_user","args":{"question":"Which package name should I use?"}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="serial"),
        activity=lambda args: "Asking user for clarification",
        validate=validate_ask_user,
        run=tool_ask_user,
    )
]

