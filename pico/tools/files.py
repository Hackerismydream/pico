"""Workspace file tools."""

from __future__ import annotations

from ..core.workspace import IGNORED_PATH_NAMES
from .spec import ToolPolicy, ToolSpec


def _path_arg(args, default="."):
    return str((args or {}).get("path", default)).strip() or default


def _activity(prefix):
    return lambda args: f"{prefix} {_path_arg(args)}"


def validate_list_files(agent, args):
    path = agent.path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("path is not a directory")


def validate_read_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    start = int(args.get("start", 1))
    end = int(args.get("end", 200))
    if start < 1 or end < start:
        raise ValueError("invalid line range")


def validate_write_file(agent, args):
    path = agent.path(args["path"])
    if path.exists() and path.is_dir():
        raise ValueError("path is a directory")
    if "content" not in args:
        raise ValueError("missing content")


def validate_write_files(agent, args):
    files = args.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("files must be a non-empty list")
    if len(files) > 30:
        raise ValueError("files must contain at most 30 entries")
    seen = set()
    for index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"file entry {index} must be an object")
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise ValueError(f"file entry {index} missing path")
        path = agent.path(path_value)
        relpath = str(path.relative_to(agent.root))
        if relpath in seen:
            raise ValueError(f"duplicate path: {relpath}")
        seen.add(relpath)
        if path.exists() and path.is_dir():
            raise ValueError(f"path is a directory: {relpath}")
        if "content" not in item:
            raise ValueError(f"file entry {index} missing content")


def validate_patch_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    old_text = str(args.get("old_text", ""))
    if not old_text:
        raise ValueError("old_text must not be empty")
    if "new_text" not in args:
        raise ValueError("missing new_text")
    text = path.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count != 1:
        raise ValueError(f"old_text must occur exactly once, found {count}")


def tool_list_files(agent, args):
    path = agent.path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("path is not a directory")
    entries = [
        item for item in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if item.name not in IGNORED_PATH_NAMES
    ]
    lines = []
    for entry in entries[:200]:
        kind = "[D]" if entry.is_dir() else "[F]"
        lines.append(f"{kind} {entry.relative_to(agent.root)}")
    return "\n".join(lines) or "(empty)"


def tool_read_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    start = int(args.get("start", 1))
    end = int(args.get("end", 200))
    if start < 1 or end < start:
        raise ValueError("invalid line range")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(f"{number:>4}: {line}" for number, line in enumerate(lines[start - 1:end], start=start))
    return f"# {path.relative_to(agent.root)}\n{body}"


def tool_write_file(agent, args):
    path = agent.path(args["path"])
    content = str(args["content"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.relative_to(agent.root)} ({len(content)} chars)"


def tool_write_files(agent, args):
    written = []
    for item in args["files"]:
        path = agent.path(item["path"])
        content = str(item["content"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(f"{path.relative_to(agent.root)} ({len(content)} chars)")
    return "wrote files:\n" + "\n".join(written)


def tool_patch_file(agent, args):
    path = agent.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    old_text = str(args.get("old_text", ""))
    if not old_text:
        raise ValueError("old_text must not be empty")
    if "new_text" not in args:
        raise ValueError("missing new_text")
    text = path.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count != 1:
        raise ValueError(f"old_text must occur exactly once, found {count}")
    path.write_text(text.replace(old_text, str(args["new_text"]), 1), encoding="utf-8")
    return f"patched {path.relative_to(agent.root)}"


TOOL_SPECS = [
    ToolSpec(
        name="list_files",
        schema={"path": "str='.'"},
        description="List files in the workspace.",
        example='<tool>{"name":"list_files","args":{"path":"."}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="parallel"),
        activity=_activity("Listing"),
        validate=validate_list_files,
        run=tool_list_files,
    ),
    ToolSpec(
        name="read_file",
        schema={"path": "str", "start": "int=1", "end": "int=200"},
        description="Read a UTF-8 file by line range.",
        example='<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>',
        policy=ToolPolicy(read_only=True, concurrency="parallel", records_read=True),
        activity=_activity("Reading"),
        validate=validate_read_file,
        run=tool_read_file,
    ),
    ToolSpec(
        name="write_file",
        schema={"path": "str", "content": "str"},
        description="Write a text file.",
        example='<tool name="write_file" path="binary_search.py"><content>def binary_search(nums, target):\n    return -1\n</content></tool>',
        risky=True,
        policy=ToolPolicy(read_only=False, concurrency="serial"),
        activity=_activity("Writing"),
        validate=validate_write_file,
        run=tool_write_file,
    ),
    ToolSpec(
        name="write_files",
        schema={"files": "list[{path:str,content:str}]"},
        description="Write multiple text files in one atomic project-scaffolding step.",
        example='<tool name="write_files"><file path="README.md"><content># Demo\n</content></file></tool>',
        risky=True,
        policy=ToolPolicy(read_only=False, concurrency="serial"),
        activity=lambda args: f"Writing {len(args.get('files', []) or [])} files",
        validate=validate_write_files,
        run=tool_write_files,
    ),
    ToolSpec(
        name="patch_file",
        schema={"path": "str", "old_text": "str", "new_text": "str"},
        description="Replace one exact text block in a file.",
        example='<tool name="patch_file" path="binary_search.py"><old_text>return -1</old_text><new_text>return mid</new_text></tool>',
        risky=True,
        policy=ToolPolicy(read_only=False, concurrency="serial", requires_prior_read=True),
        activity=_activity("Patching"),
        validate=validate_patch_file,
        run=tool_patch_file,
    ),
]

