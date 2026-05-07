"""Local skill discovery, catalog rendering, and invocation parsing."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.workspace import clip


MAX_SKILL_SUMMARY_CHARS = 2400
MAX_SKILL_ENTRY_CHARS = 280

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    when_to_use: str
    triggers: tuple[str, ...]
    argument_hint: str
    arguments: tuple[str, ...]
    user_invocable: bool
    model_invocable: bool
    context: str
    paths: tuple[str, ...]
    source: str
    file_path: Path
    skill_dir: Path
    content: str
    content_hash: str

    def command_name(self) -> str:
        return f"/skill:{self.name}"

    def body_with_args(self, args: str = "") -> str:
        skill_dir = str(self.skill_dir)
        text = self.content.replace("$ARGUMENTS", str(args or ""))
        text = text.replace("${PICO_SKILL_DIR}", skill_dir)
        return text

    def invocation_block(self, args: str = "") -> str:
        body = self.body_with_args(args)
        lines = [
            f'<skill name="{self.name}" source="{self.source}" context="{self.context}">',
            f"Base directory for this skill: {self.skill_dir}",
        ]
        if args:
            lines.append(f"Arguments: {args}")
        lines.extend(["", body, "</skill>"])
        return "\n".join(lines).strip()


@dataclass(frozen=True)
class SkillCommand:
    name: str
    args: str
    raw: str


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()
    raw = match.group(1)
    body = text[match.end() :].strip()
    metadata: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        metadata[key.strip().lower().replace("-", "_")] = _parse_value(value.strip())
    return metadata, body


def _parse_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "yes", "1"}:
        return True
    if lowered in {"false", "no", "0"}:
        return False
    if "," in value:
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (tuple, list)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"true", "yes", "1", "on"}


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def parse_skill_command(text: str) -> SkillCommand | None:
    raw = str(text or "").strip()
    if not raw.startswith("/skill"):
        return None
    if raw.startswith("/skill:"):
        body = raw[len("/skill:") :].strip()
    elif raw == "/skill" or raw.startswith("/skill "):
        body = raw[len("/skill") :].strip()
    else:
        return None
    if not body:
        return None
    try:
        tokens = shlex.split(body)
    except ValueError:
        return None
    if not tokens:
        return None
    name = tokens[0]
    args = " ".join(tokens[1:])
    name = name.strip().lstrip("/")
    if not name:
        return None
    return SkillCommand(name=name, args=args.strip(), raw=raw)


class SkillCatalog:
    def __init__(self, workspace_root, skill_roots=None):
        self.workspace_root = Path(workspace_root)
        roots = skill_roots or (
            self.workspace_root / ".pico" / "skills",
            self.workspace_root / "skills",
        )
        self.skill_roots = tuple(Path(root) for root in roots)
        self.last_diagnostics: list[dict] = []

    def discover(self) -> list[SkillDefinition]:
        diagnostics: list[dict] = []
        skills: list[SkillDefinition] = []
        seen: dict[str, SkillDefinition] = {}
        for root in self.skill_roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("*/SKILL.md")):
                try:
                    skill = self._load_skill(path)
                except Exception as exc:
                    diagnostics.append({"type": "warning", "path": self._source_for(path), "message": str(exc)})
                    continue
                if not skill.name:
                    diagnostics.append({"type": "warning", "path": self._source_for(path), "message": "skill name is empty"})
                    continue
                existing = seen.get(skill.name)
                if existing is not None:
                    diagnostics.append(
                        {
                            "type": "collision",
                            "name": skill.name,
                            "winner": existing.source,
                            "loser": skill.source,
                        }
                    )
                    continue
                seen[skill.name] = skill
                skills.append(skill)
        self.last_diagnostics = diagnostics
        return skills

    def _load_skill(self, path: Path) -> SkillDefinition:
        text = path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(text)
        name = _as_str(metadata.get("name"), path.parent.name).strip() or path.parent.name
        description = _as_str(metadata.get("description"))
        when_to_use = _as_str(metadata.get("when_to_use"))
        triggers = _as_tuple(metadata.get("triggers")) or (name,)
        context = _as_str(metadata.get("context"), "inline").strip().lower() or "inline"
        if context not in {"inline", "fork"}:
            raise ValueError(f"invalid context for {name}: {context}")
        content = body or text.strip()
        return SkillDefinition(
            name=name,
            description=description,
            when_to_use=when_to_use,
            triggers=tuple(trigger.lower() for trigger in triggers),
            argument_hint=_as_str(metadata.get("argument_hint")),
            arguments=_as_tuple(metadata.get("arguments")),
            user_invocable=_as_bool(metadata.get("user_invocable"), True),
            model_invocable=_as_bool(metadata.get("model_invocable"), True),
            context=context,
            paths=_as_tuple(metadata.get("paths")),
            source=self._source_for(path),
            file_path=path,
            skill_dir=path.parent,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    def _source_for(self, path: Path) -> str:
        try:
            return path.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return str(path)

    def get(self, name: str) -> SkillDefinition | None:
        normalized = str(name or "").strip().lower().lstrip("/")
        for skill in self.discover():
            if skill.name.lower() == normalized:
                return skill
        return None

    def legacy_matches(self, user_message: str, limit: int = 3) -> list[SkillDefinition]:
        query = str(user_message or "").lower()
        matches = []
        for skill in self.discover():
            explicit_names = (f"@{skill.name.lower()}", f"/{skill.name.lower()}")
            if any(marker in query for marker in explicit_names) or any(trigger and trigger in query for trigger in skill.triggers):
                matches.append(skill)
            if len(matches) >= limit:
                break
        return matches

    def render_prompt(self, available: list[SkillDefinition] | None = None, invoked: list[dict] | None = None) -> str:
        available = list(self.discover() if available is None else available)
        invoked = list(invoked or [])
        visible = [skill for skill in available if skill.model_invocable]
        if not visible and not invoked:
            return ""
        lines = []
        if visible:
            lines.extend(
                [
                    "Available skills:",
                    "- These are reusable workflow instructions. Do not assume their full contents.",
                    "- Use list_skills(query) for full catalog discovery and load_skill(name,args) only when full instructions are relevant.",
                    "- Users can explicitly load a skill with /skill:<name>.",
                ]
            )
            total = 0
            for skill in visible:
                entry = self._summary_entry(skill)
                if total + len(entry) > MAX_SKILL_SUMMARY_CHARS:
                    lines.append("- ... additional skills omitted by budget")
                    break
                lines.append(entry)
                total += len(entry)
        if invoked:
            if lines:
                lines.append("")
            lines.append("Loaded skills:")
            for item in invoked:
                if item.get("content"):
                    lines.append(str(item["content"]))
                else:
                    lines.append(f"- {item.get('name', '')} ({item.get('source', '')})")
        return "\n".join(lines).strip()

    def _summary_entry(self, skill: SkillDefinition) -> str:
        command = skill.command_name()
        if skill.argument_hint:
            command += f" <{skill.argument_hint}>"
        desc = skill.description or "(no description)"
        details = []
        if skill.when_to_use:
            details.append(f"when: {skill.when_to_use}")
        details.append(f"source: {skill.source}")
        text = f"- {command}: {desc} ({'; '.join(details)})"
        return clip(text, MAX_SKILL_ENTRY_CHARS)

    def metadata(
        self,
        available: list[SkillDefinition] | None = None,
        legacy_matches: list[SkillDefinition] | None = None,
        invoked: list[dict] | None = None,
    ) -> dict:
        available = list(self.discover() if available is None else available)
        legacy_matches = list(legacy_matches or [])
        invoked = list(invoked or [])
        visible = [skill for skill in available if skill.model_invocable]
        return {
            "available_count": len(available),
            "visible": [self._skill_meta(skill) for skill in visible],
            "legacy_matches": [self._skill_meta(skill) for skill in legacy_matches],
            "invoked": [
                {
                    "name": item.get("name", ""),
                    "source": item.get("source", ""),
                    "context": item.get("context", ""),
                    "invocation_source": item.get("invocation_source", ""),
                    "args": item.get("args", ""),
                    "rendered_chars": int(item.get("rendered_chars", 0) or 0),
                }
                for item in invoked
            ],
            "selected": [],
            "selected_count": 0,
            "diagnostics": list(self.last_diagnostics),
        }

    @staticmethod
    def _skill_meta(skill: SkillDefinition) -> dict:
        return {
            "name": skill.name,
            "source": skill.source,
            "description": skill.description,
            "when_to_use": skill.when_to_use,
            "context": skill.context,
        }

    def summaries(
        self,
        query: str = "",
        limit: int = 50,
        *,
        model_invocable: bool | None = None,
        user_invocable: bool | None = None,
    ) -> list[str]:
        query = str(query or "").strip().lower()
        limit = max(1, min(int(limit or 50), 100))
        results = []
        for skill in self.discover():
            if model_invocable is not None and skill.model_invocable != model_invocable:
                continue
            if user_invocable is not None and skill.user_invocable != user_invocable:
                continue
            haystack = " ".join(
                [
                    skill.name,
                    skill.description,
                    skill.when_to_use,
                    " ".join(skill.triggers),
                    skill.source,
                ]
            ).lower()
            if query and query not in haystack:
                continue
            results.append(self._summary_entry(skill))
            if len(results) >= limit:
                break
        return results

    def signature(self) -> str:
        payload = [
            {
                "name": skill.name,
                "description": skill.description,
                "when_to_use": skill.when_to_use,
                "triggers": list(skill.triggers),
                "argument_hint": skill.argument_hint,
                "arguments": list(skill.arguments),
                "user_invocable": skill.user_invocable,
                "model_invocable": skill.model_invocable,
                "context": skill.context,
                "paths": list(skill.paths),
                "source": skill.source,
                "content_hash": skill.content_hash,
            }
            for skill in self.discover()
        ]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    # Compatibility with the previous SkillLoader surface.
    def select(self, user_message, limit=3):
        return self.legacy_matches(user_message, limit=limit)

    def render(self, selected):
        return self.render_prompt(list(selected), [])


SkillLoader = SkillCatalog
