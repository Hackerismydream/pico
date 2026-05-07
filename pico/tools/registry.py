"""Tool registry assembly.

The registry is intentionally thin: concrete tools live in family modules and
export `ToolSpec` objects. This module only collects specs, applies runtime
visibility rules, and adapts specs to the dict protocol expected by `Pico`.
"""

from __future__ import annotations

from . import files, interaction, search, shell, skills, subagents, tasks
from .files import (
    tool_list_files as tool_list_files,
    tool_patch_file as tool_patch_file,
    tool_read_file as tool_read_file,
    tool_write_file as tool_write_file,
    tool_write_files as tool_write_files,
)
from .interaction import tool_ask_user as tool_ask_user
from .search import tool_glob as tool_glob, tool_grep as tool_grep, tool_search as tool_search
from .shell import tool_run_shell as tool_run_shell
from .subagents import (
    tool_agent as tool_agent,
    tool_delegate as tool_delegate,
    tool_send_message as tool_send_message,
    tool_task_stop as tool_task_stop,
)
from .tasks import (
    tool_todo_list as tool_todo_list,
    tool_todo_update as tool_todo_update,
    tool_todo_write as tool_todo_write,
)


def all_tool_specs():
    return [
        *files.TOOL_SPECS,
        *search.TOOL_SPECS,
        *interaction.TOOL_SPECS,
        *shell.TOOL_SPECS,
        *tasks.TOOL_SPECS,
        *skills.TOOL_SPECS,
        *subagents.TOOL_SPECS,
    ]


def tool_specs_by_name():
    specs = {}
    for spec in all_tool_specs():
        if spec.name in specs:
            raise ValueError(f"duplicate tool spec: {spec.name}")
        specs[spec.name] = spec
    return specs


def is_allowed(allowed_tools, name):
    if allowed_tools is None:
        return True
    return str(name) in set(allowed_tools)


def build_tool_registry(agent):
    allowed_tools = getattr(agent, "allowed_tools", None)
    specs = tool_specs_by_name()
    skills_enabled = not hasattr(agent, "feature_enabled") or agent.feature_enabled("skills")
    tools = {
        name: spec.materialize(agent)
        for name, spec in specs.items()
        if name != "delegate"
        if skills_enabled or name not in {"list_skills", "load_skill"}
        if is_allowed(allowed_tools, name)
    }
    if agent.depth < agent.max_depth and is_allowed(allowed_tools, "delegate"):
        tools["delegate"] = specs["delegate"].materialize(agent)
    return tools


def tool_example(name):
    spec = tool_specs_by_name().get(str(name))
    return str(spec.example) if spec else ""


def tool_activity_description(name, args=None):
    spec = tool_specs_by_name().get(str(name))
    if not spec:
        return f"Running {name}"
    return spec.activity_description(args or {})


def validate_tool(agent, name, args):
    spec = tool_specs_by_name().get(str(name))
    if spec is None:
        return
    if spec.validate:
        spec.validate(agent, args or {})
