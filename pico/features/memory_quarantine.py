"""Quarantine rules for durable memory notes."""

import re

from .memory_lint import SECRET_PATTERNS

QUARANTINE_PATTERNS = [
    re.compile(r"ignore previous instructions", re.I),
    re.compile(r"ignore prior instructions", re.I),
    re.compile(r"</?(system|assistant)>", re.I),
    re.compile(r"disregard all earlier", re.I),
    re.compile(r"new instructions:", re.I),
    re.compile(r"you are now", re.I),
]


def should_quarantine(note_text):
    text = str(note_text)
    return any(pattern.search(text) for pattern in QUARANTINE_PATTERNS) or any(
        pattern.search(text) for pattern in SECRET_PATTERNS
    )
