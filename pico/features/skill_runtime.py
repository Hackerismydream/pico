"""Skill invocation runtime for inline and forked Pico skills."""

from __future__ import annotations

from ..core.workspace import clip


class SkillRuntime:
    def __init__(self, agent, catalog) -> None:
        self.agent = agent
        self.catalog = catalog

    def invoke(self, name: str, args: str = "", invocation_source: str = "model") -> str:
        skill = self.catalog.get(name)
        if skill is None:
            raise ValueError(f"unknown skill: {name}")
        if invocation_source == "user" and not skill.user_invocable:
            raise ValueError(f"skill is not user invocable: {skill.name}")
        if invocation_source == "model" and not skill.model_invocable:
            raise ValueError(f"skill is not model invocable: {skill.name}")

        args = str(args or "").strip()
        content = skill.invocation_block(args)
        metadata = {
            "name": skill.name,
            "source": skill.source,
            "context": skill.context,
            "invocation_source": invocation_source,
            "args": args,
            "rendered_chars": len(content),
            "include_in_prompt": skill.context == "inline",
            "content": content if skill.context == "inline" else "",
        }
        self.agent.record_skill_invoked(metadata)
        if skill.context == "fork":
            return self._invoke_fork(skill, args, content)
        return content

    def _invoke_fork(self, skill, args: str, content: str) -> str:
        description = f"skill:{skill.name}"
        if args:
            description += f" {clip(args, 80)}"
        payload = self.agent.subagent_manager.spawn(
            description=description,
            prompt=content,
            subagent_type="Explore",
            background=False,
            max_steps=8,
        )
        self.agent.deliver_subagent_notification(payload)
        status = str(payload.get("status", "completed"))
        result = str(payload.get("result") or payload.get("error") or "")
        return f"forked skill {skill.name} completed with status={status}\n{result}".strip()
