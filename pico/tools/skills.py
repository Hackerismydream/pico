"""Skill loading tool."""

from __future__ import annotations

from .spec import Effect, ToolPolicy, ToolSpec


def _ensure_skills_enabled(agent):
    if hasattr(agent, "feature_enabled") and not agent.feature_enabled("skills"):
        raise ValueError("skills are disabled")


def validate_load_skill(agent, args):
    _ensure_skills_enabled(agent)
    name = str((args or {}).get("name", "")).strip()
    if not name:
        raise ValueError("name must not be empty")
    skill = agent.skill_catalog.get(name)
    if skill is None:
        raise ValueError(f"unknown skill: {name}")
    if not skill.model_invocable:
        raise ValueError(f"skill is not model invocable: {name}")


def tool_load_skill(agent, args):
    return agent.load_skill(
        str((args or {}).get("name", "")).strip(),
        str((args or {}).get("args", "")).strip(),
        invocation_source="model",
    )


def validate_list_skills(agent, args):
    _ensure_skills_enabled(agent)


def tool_list_skills(agent, args):
    query = str((args or {}).get("query", "")).strip()
    try:
        limit = int((args or {}).get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    entries = agent.skill_catalog.summaries(query=query, limit=limit, model_invocable=True)
    if not entries:
        return "Available skills: none"
    header = "Available skills"
    if query:
        header += f' matching "{query}"'
    return "\n".join([header + ":", *entries])


TOOL_SPECS = [
    ToolSpec(
        name="list_skills",
        schema={"query": "str=''", "limit": "int=50"},
        description="List available Pico skills by summary without loading full skill bodies.",
        example='<tool>{"name":"list_skills","args":{"query":"pytest","limit":20}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="parallel", max_result_chars=12000, effects=(Effect.RUNTIME_STATE_READ,)),
        activity=lambda args: f"Listing skills matching {str(args.get('query', '')).strip()}" if str(args.get("query", "")).strip() else "Listing skills",
        validate=validate_list_skills,
        run=tool_list_skills,
    ),
    ToolSpec(
        name="load_skill",
        schema={"name": "str", "args": "str=''", "context": "inline|fork?"},
        description="Load a Pico skill's full instructions by name after matching its catalog summary.",
        example='<tool>{"name":"load_skill","args":{"name":"pytest","args":"tests/test_pico.py"}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="serial", max_result_chars=12000, effects=(Effect.RUNTIME_STATE_WRITE,)),
        activity=lambda args: f"Loading skill {str(args.get('name', '')).strip()}" if str(args.get("name", "")).strip() else "Loading skill",
        validate=validate_load_skill,
        run=tool_load_skill,
    )
]
