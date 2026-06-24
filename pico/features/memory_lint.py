"""Static memory lint primitives shared by future memory validators."""

import re

_KEYWORD = r"(?:key|token|secret|password|api)"
_LONG_HEX = r"[A-Fa-f0-9]{32,}"
_LONG_BASE64 = r"[A-Za-z0-9+/]{40,}={0,2}"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(
        rf"(?i)(?:{_KEYWORD}.{{0,20}}(?:{_LONG_HEX}|{_LONG_BASE64})|(?:{_LONG_HEX}|{_LONG_BASE64}).{{0,20}}{_KEYWORD})"
    ),
]
