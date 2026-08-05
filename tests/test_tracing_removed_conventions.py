"""Pin that new traces cannot resurrect a removed subsystem's conventions.

Scans the *span names* Pico emits — every ``trace.span(...)`` /
``trace.instrument(...)`` literal under ``pico/**`` plus the viewer descriptor
``type`` values — and fails when one names a subsystem the runtime removed.
Matching span names rather than arbitrary source text keeps an unrelated
identifier from tripping the guard and keeps a real emission from hiding behind
one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pico

_ROOT = Path(pico.__file__).resolve().parent
_DESCRIPTORS = _ROOT / "tracing" / "viewer" / "descriptors"

_EMISSION = re.compile(r"trace\.(?:span|instrument)\(\s*(['\"])([^'\"]+)\1")

# Conventions removed from the runtime, written without separators because the
# comparison normalizes both sides (so ``skill_hub`` and ``skill.hub`` both hit
# ``skillhub``). This list grows when a subsystem is removed; it is never
# shortened to make the test pass.
_REMOVED = (
    "sentinel",
    "heartbeat",
    "nudge",
    "skillhub",
    "deepresearch",
    "discord",
    "slack",
    "telegram",
    "whatsapp",
)


def _normalized(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _emitted_span_names() -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    for path in _ROOT.rglob("*.py"):
        for match in _EMISSION.finditer(path.read_text(encoding="utf-8")):
            names.setdefault(match.group(2), []).append(str(path.relative_to(_ROOT)))
    return names


def _descriptor_types() -> dict[str, list[str]]:
    types: dict[str, list[str]] = {}
    for path in sorted(_DESCRIPTORS.glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            value = entry.get("type")
            if isinstance(value, str):
                types.setdefault(value, []).append(str(path.relative_to(_ROOT)))
    return types


def _offenders(names: dict[str, list[str]]) -> list[str]:
    hits = []
    for name, sources in names.items():
        flat = _normalized(name)
        for removed in _REMOVED:
            if _normalized(removed) in flat:
                hits.append(f"{name} ({removed}) in {', '.join(sorted(set(sources)))}")
    return sorted(hits)


def test_the_scan_finds_the_real_emission_sites():
    # Guards the guard: a regex that silently matched nothing would pass forever.
    names = _emitted_span_names()
    assert {"session.turn", "spine.turn", "llm.call", "tool.call", "channel.deliver"} <= set(names)


def test_no_emitted_span_name_references_a_removed_convention():
    assert _offenders(_emitted_span_names()) == []


def test_no_viewer_descriptor_references_a_removed_convention():
    types = _descriptor_types()
    assert types  # the descriptor set is non-empty, so the scan is meaningful
    assert _offenders(types) == []


def test_the_detector_would_catch_a_reintroduced_convention():
    assert _offenders({"pico.sentinel.tick": ["x.py"]}) == ["pico.sentinel.tick (sentinel) in x.py"]
    assert _offenders({"skill.hub.sync": ["x.py"]}) == ["skill.hub.sync (skillhub) in x.py"]
    assert _offenders({"session.turn": ["x.py"]}) == []
