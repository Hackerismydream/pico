"""Workspace search tools."""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess

from ..core.workspace import IGNORED_PATH_NAMES
from .spec import ToolPolicy, ToolSpec


def _path_arg(args, default="."):
    return str((args or {}).get("path", default)).strip() or default


def _is_visible_workspace_path(agent, path):
    try:
        relative = path.relative_to(agent.root)
    except ValueError:
        return False
    return not any(part in IGNORED_PATH_NAMES for part in relative.parts)


def _iter_visible_files(agent, path):
    if path.is_file():
        return [path] if _is_visible_workspace_path(agent, path) else []
    return [
        item
        for item in path.rglob("*")
        if item.is_file() and _is_visible_workspace_path(agent, item)
    ]


def validate_glob(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = agent.path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("path is not a directory")
    limit = int(args.get("limit", 200))
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be in [1, 1000]")


def validate_grep(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = agent.path(args.get("path", "."))
    if not path.exists():
        raise ValueError("path does not exist")
    context = int(args.get("context", 0))
    if context < 0 or context > 20:
        raise ValueError("context must be in [0, 20]")
    limit = int(args.get("limit", 200))
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be in [1, 1000]")


def validate_search(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    agent.path(args.get("path", "."))


def tool_glob(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = agent.path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("path is not a directory")
    limit = int(args.get("limit", 200))
    matches = []
    for item in path.rglob(pattern):
        if not _is_visible_workspace_path(agent, item):
            continue
        relative = item.relative_to(agent.root).as_posix()
        matches.append(relative + ("/" if item.is_dir() else ""))
        if len(matches) >= limit:
            break
    return "\n".join(sorted(matches)) or "(no matches)"


def tool_grep(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = agent.path(args.get("path", "."))
    if not path.exists():
        raise ValueError("path does not exist")
    if not _is_visible_workspace_path(agent, path):
        return "(no matches)"
    file_glob = str(args.get("glob", "")).strip()
    context = int(args.get("context", 0))
    limit = int(args.get("limit", 200))
    case_sensitive = bool(args.get("case_sensitive", False))

    if shutil.which("rg"):
        command = ["rg", "-n", "--color=never", "--max-count", str(limit)]
        command.append("--case-sensitive" if case_sensitive else "--smart-case")
        if context:
            command.extend(["-C", str(context)])
        if file_glob:
            command.extend(["--glob", file_glob])
        for ignored in sorted(IGNORED_PATH_NAMES):
            command.extend(["--glob", f"!{ignored}/**", "--glob", f"!**/{ignored}/**"])
        command.extend([pattern, str(path)])
        result = subprocess.run(command, cwd=agent.root, capture_output=True, text=True)
        lines = (result.stdout.strip() or result.stderr.strip()).splitlines()
        return "\n".join(lines[:limit]) or "(no matches)"

    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)
    matches = []
    for file_path in _iter_visible_files(agent, path):
        relative = file_path.relative_to(agent.root).as_posix()
        if file_glob and not fnmatch.fnmatch(relative, file_glob):
            continue
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, start=1):
            if compiled.search(line):
                matches.append(f"{relative}:{number}:{line}")
                if len(matches) >= limit:
                    return "\n".join(matches)
    return "\n".join(matches) or "(no matches)"


def tool_search(agent, args):
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = agent.path(args.get("path", "."))
    if not _is_visible_workspace_path(agent, path):
        return "(no matches)"

    if shutil.which("rg"):
        command = ["rg", "-n", "--smart-case", "--max-count", "200"]
        for ignored in sorted(IGNORED_PATH_NAMES):
            command.extend(["--glob", f"!{ignored}/**", "--glob", f"!**/{ignored}/**"])
        command.extend([pattern, str(path)])
        result = subprocess.run(command, cwd=agent.root, capture_output=True, text=True)
        return result.stdout.strip() or result.stderr.strip() or "(no matches)"

    matches = []
    for file_path in _iter_visible_files(agent, path):
        for number, line in enumerate(file_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if pattern.lower() in line.lower():
                matches.append(f"{file_path.relative_to(agent.root)}:{number}:{line}")
                if len(matches) >= 200:
                    return "\n".join(matches)
    return "\n".join(matches) or "(no matches)"


TOOL_SPECS = [
    ToolSpec(
        name="glob",
        schema={"pattern": "str", "path": "str='.'", "limit": "int=200"},
        description="Find files by glob pattern, recursively, while hiding internal agent state.",
        example='<tool>{"name":"glob","args":{"pattern":"**/*.py","path":"."}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="parallel"),
        activity=lambda args: f"Finding files matching {str(args.get('pattern', '')).strip() or 'pattern'}",
        validate=validate_glob,
        run=tool_glob,
    ),
    ToolSpec(
        name="grep",
        schema={"pattern": "str", "path": "str='.'", "glob": "str?", "case_sensitive": "bool=False", "context": "int=0", "limit": "int=200"},
        description="Search file contents with rg-style output; optionally filter files by glob.",
        example='<tool>{"name":"grep","args":{"pattern":"class Pico","path":"pico","glob":"*.py"}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="parallel"),
        activity=lambda args: f"Searching text {str(args.get('pattern', '')).strip() or 'pattern'} in {_path_arg(args)}",
        validate=validate_grep,
        run=tool_grep,
    ),
    ToolSpec(
        name="search",
        schema={"pattern": "str", "path": "str='.'"},
        description="Search the workspace with rg or a simple fallback.",
        example='<tool>{"name":"search","args":{"pattern":"binary_search","path":"."}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="parallel"),
        activity=lambda args: f"Searching {str(args.get('pattern', '')).strip() or 'pattern'} in {_path_arg(args)}",
        validate=validate_search,
        run=tool_search,
    ),
]

