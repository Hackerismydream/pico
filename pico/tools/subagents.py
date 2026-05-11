"""Subagent orchestration tools."""

from __future__ import annotations

import json
from .spec import ToolPolicy, ToolSpec


def validate_delegate(agent, args):
    task = str(args.get("task", "")).strip()
    if not task:
        raise ValueError("task must not be empty")


def validate_agent(agent, args):
    description = str(args.get("description", "")).strip()
    prompt = str(args.get("prompt", "")).strip()
    if not description:
        raise ValueError("description must not be empty")
    if not prompt:
        raise ValueError("prompt must not be empty")
    subagent_type = str(args.get("subagent_type", "Explore")).strip() or "Explore"
    if subagent_type.lower() not in {"explore", "worker"}:
        raise ValueError("subagent_type must be Explore or Worker")
    if subagent_type.lower() == "worker":
        write_scope = args.get("write_scope")
        if not isinstance(write_scope, list) or not write_scope:
            raise ValueError("write_scope is required for Worker subagents")
    if "max_steps" in args:
        max_steps = int(args.get("max_steps", 0))
        if max_steps < 1 or max_steps > 80:
            raise ValueError("max_steps must be in [1, 80]")


def validate_send_message(agent, args):
    if not str(args.get("to", "")).strip():
        raise ValueError("to must not be empty")
    if not str(args.get("message", "")).strip():
        raise ValueError("message must not be empty")


def validate_task_stop(agent, args):
    if not str(args.get("task_id", "")).strip():
        raise ValueError("task_id must not be empty")


def tool_delegate(agent, args):
    if agent.depth >= agent.max_depth:
        raise ValueError("delegate depth exceeded")
    task = str(args.get("task", "")).strip()
    if not task:
        raise ValueError("task must not be empty")
    payload = agent.subagent_manager.spawn(
        description=task,
        prompt=task,
        subagent_type="Explore",
        max_steps=int(args.get("max_steps", 3)),
        background=False,
    )
    agent.deliver_subagent_notification(payload)
    return "delegate_result:\n" + str(payload.get("result", ""))


def tool_agent(agent, args):
    payload = agent.subagent_manager.spawn(
        description=str(args.get("description", "")),
        prompt=str(args.get("prompt", "")),
        subagent_type=str(args.get("subagent_type", "Explore")),
        write_scope=list(args.get("write_scope") or []),
        max_steps=int(args.get("max_steps", 0) or 0),
        background=bool(args.get("background", True)),
    )
    if payload.get("status") == "started":
        agent.record_subagent_started(payload)
    else:
        agent.deliver_subagent_notification(payload)
    return json.dumps(payload, ensure_ascii=False)


def tool_send_message(agent, args):
    payload = agent.subagent_manager.continue_task(
        task_id=str(args.get("to", "")),
        message=str(args.get("message", "")),
        background=bool(args.get("background", True)),
    )
    if payload.get("status") == "started":
        agent.record_subagent_started(payload)
    else:
        agent.deliver_subagent_notification(payload)
    return json.dumps(payload, ensure_ascii=False)


def tool_task_stop(agent, args):
    payload = agent.subagent_manager.stop_task(str(args.get("task_id", "")))
    return json.dumps(payload, ensure_ascii=False)


TOOL_SPECS = [
    ToolSpec(
        name="delegate",
        schema={"task": "str", "max_steps": "int=3"},
        description="Ask a bounded read-only child agent to investigate.",
        example='<tool>{"name":"delegate","args":{"task":"inspect README.md","max_steps":3}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="serial"),
        activity=lambda args: "Delegating read-only investigation",
        validate=validate_delegate,
        run=tool_delegate,
    ),
    ToolSpec(
        name="agent",
        schema={
            "description": "str",
            "prompt": "str",
            "subagent_type": "Explore|Worker='Explore'",
            "background": "bool=True",
            "write_scope": "list[str]=[]",
            "max_steps": "int?",
        },
        description="Launch a bounded subagent for exploration or scoped worker tasks.",
        example='<tool>{"name":"agent","args":{"description":"Inspect runtime","prompt":"Find the runtime entry points and report file paths.","subagent_type":"Explore"}}</tool>',
        risky=True,
        policy=ToolPolicy(read_only=False, concurrency="serial"),
        activity=lambda args: f"Launching subagent: {str(args.get('description', '')).strip()}" if str(args.get("description", "")).strip() else "Launching subagent",
        validate=validate_agent,
        run=tool_agent,
    ),
    ToolSpec(
        name="send_message",
        schema={"to": "str", "message": "str", "background": "bool=True"},
        description="Continue an existing subagent with a self-contained message.",
        example='<tool>{"name":"send_message","args":{"to":"agent-1234abcd","message":"Read pico/runtime.py and report the ask loop only."}}</tool>',
        risky=True,
        policy=ToolPolicy(read_only=False, concurrency="serial"),
        activity=lambda args: f"Continuing subagent {str(args.get('to', '')).strip()}" if str(args.get("to", "")).strip() else "Continuing subagent",
        validate=validate_send_message,
        run=tool_send_message,
    ),
    ToolSpec(
        name="task_stop",
        schema={"task_id": "str"},
        description="Stop a running subagent.",
        example='<tool>{"name":"task_stop","args":{"task_id":"agent-1234abcd"}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="serial"),
        activity=lambda args: f"Stopping subagent {str(args.get('task_id', '')).strip()}" if str(args.get("task_id", "")).strip() else "Stopping subagent",
        validate=validate_task_stop,
        run=tool_task_stop,
    ),
]
