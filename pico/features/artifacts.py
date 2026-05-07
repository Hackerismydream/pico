"""Generic runtime artifact graph helpers.

The graph is evidence about what the agent touched. It deliberately avoids
business-specific rules such as "student manager must use FastAPI".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

MAX_PATHS_PER_KIND = 80
MAX_API_ITEMS = 80
READ_LIMIT = 24000

PATH_KINDS = ("backend", "frontend", "docs", "tests", "dependencies", "other")
BACKEND_FILE_NAMES = {"app.py", "main.py", "server.py", "api.py", "routes.py"}
DEPENDENCY_FILE_NAMES = {"package.json", "pyproject.toml", "requirements.txt", "uv.lock", "pnpm-lock.yaml", "yarn.lock"}
FRONTEND_SUFFIXES = {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
BACKEND_SUFFIXES = {".py", ".go", ".rs", ".java", ".kt", ".cs", ".rb", ".php"}
STRING_PATH_PATTERN = re.compile(r"""['"`](?P<path>(?:https?://[^'"`\s)]+)|(?:/[^'"`\s)]*))['"`]""")
TEMPLATE_PATH_PATTERN = re.compile(r"""\$\{[^}]+\}(?P<path>/[A-Za-z0-9_./{}:$?&=-]+)""")
ROUTE_DECORATOR_PATTERN = re.compile(r"""@\w+(?:\.\w+)*\.(?:get|post|put|delete|patch|route)\(\s*['"](?P<path>/[^'"]*)['"]""")


def classify_path(path: str) -> str:
    rel = Path(str(path))
    parts = {part.lower() for part in rel.parts}
    name = rel.name.lower()
    suffix = rel.suffix.lower()
    if name in DEPENDENCY_FILE_NAMES:
        return "dependencies"
    if name.startswith("readme") or suffix in {".md", ".rst"} or "docs" in parts:
        return "docs"
    if "test" in parts or "tests" in parts or name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.ts"):
        return "tests"
    if parts & {"frontend", "client", "web", "ui", "static", "public", "src"} and suffix in FRONTEND_SUFFIXES:
        return "frontend"
    if suffix in FRONTEND_SUFFIXES:
        return "frontend"
    if parts & {"backend", "api", "server", "services"}:
        return "backend"
    if name in BACKEND_FILE_NAMES or suffix in BACKEND_SUFFIXES:
        return "backend"
    return "other"


def _bounded_unique(values: list[str], limit: int = MAX_API_ITEMS) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
        if len(output) >= limit:
            break
    return output


def _read_text(root: Path, relpath: str) -> str:
    try:
        path = (root / relpath).resolve()
        path.relative_to(root.resolve())
    except Exception:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:READ_LIMIT]
    except Exception:
        return ""


def _extract_path_literals(text: str) -> list[str]:
    values = [match.group("path") for match in STRING_PATH_PATTERN.finditer(text or "")]
    values.extend(match.group("path") for match in TEMPLATE_PATH_PATTERN.finditer(text or ""))
    values.extend(match.group("path") for match in ROUTE_DECORATOR_PATTERN.finditer(text or ""))
    normalized = []
    for value in values:
        parsed = urlparse(value)
        path = parsed.path if parsed.scheme and parsed.netloc else value
        if path.startswith("/${"):
            continue
        normalized.append(path)
    return _bounded_unique([value for value in normalized if value])


def _latest_passed_checked_paths(verifications: list[dict] | None) -> set[str]:
    for artifact in reversed(list(verifications or [])):
        if artifact.get("status") != "passed":
            continue
        checked_paths = {str(path) for path in artifact.get("checked_paths", []) or [] if str(path)}
        if checked_paths:
            return checked_paths
    return set()


def build_artifact_graph(root, changed_paths: list[str] | None, verifications: list[dict] | None = None) -> dict:
    root = Path(root)
    paths = {kind: [] for kind in PATH_KINDS}
    artifacts = []
    backend_routes = []
    frontend_references = []
    checked_paths = _latest_passed_checked_paths(verifications)
    unique_paths = _bounded_unique([str(path) for path in (changed_paths or [])], MAX_PATHS_PER_KIND * 2)
    for relpath in unique_paths:
        kind = classify_path(relpath)
        if len(paths[kind]) < MAX_PATHS_PER_KIND:
            paths[kind].append(relpath)
        artifacts.append(
            {
                "path": relpath,
                "kind": kind,
                "status": "verified" if relpath in checked_paths else ("stale" if checked_paths else "changed"),
                "evidence": [
                    {"type": "verification", "status": "passed"}
                ]
                if relpath in checked_paths
                else [],
            }
        )
        text = _read_text(root, relpath)
        if not text:
            continue
        literals = _extract_path_literals(text)
        if kind == "backend":
            backend_routes.extend(literals)
        elif kind == "frontend":
            frontend_references.extend(literals)
    requirements = []
    if any(str(path).endswith(".py") for path in paths["backend"] + paths["tests"]):
        requirements.append("python_syntax_or_tests")
    if paths["frontend"] or any(str(path).endswith("package.json") for path in paths["dependencies"]):
        requirements.append("package_build_or_test")
    if backend_routes and frontend_references:
        requirements.append("api_consistency")
    if paths["docs"]:
        requirements.append("docs_startup_consistency")
    return {
        "schema_version": "artifact-graph-v1",
        "artifacts": artifacts,
        "paths": paths,
        "summary": {kind: len(paths[kind]) for kind in PATH_KINDS},
        "api": {
            "backend_routes": _bounded_unique(backend_routes),
            "frontend_references": _bounded_unique(frontend_references),
        },
        "verification_requirements": _bounded_unique(requirements),
    }


def _project_has_tests(root: Path) -> bool:
    candidates = ("tests", "test")
    if any((root / name).exists() for name in candidates):
        return True
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.startswith("test_") or name.endswith((".test.ts", ".test.js", ".spec.ts", ".spec.js")):
            return True
    return False


def _package_scripts(root: Path) -> dict:
    path = root / "package.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    scripts = data.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def suggest_verification_commands(root, artifact_graph: dict | None = None) -> list[dict]:
    root = Path(root)
    graph = artifact_graph or {}
    path_groups = graph.get("paths", {}) if isinstance(graph, dict) else {}
    suggestions = []
    scripts = _package_scripts(root)
    if scripts.get("test"):
        suggestions.append({"command": "npm test", "reason": "package.json defines a test script"})
    if scripts.get("build"):
        suggestions.append({"command": "npm run build", "reason": "package.json defines a build script"})
    python_paths = list(path_groups.get("backend", []) or []) + list(path_groups.get("tests", []) or [])
    has_python = any(str(path).endswith(".py") for path in python_paths)
    python_prefix = "uv run --with-requirements requirements.txt" if (root / "requirements.txt").is_file() else "uv run"
    if _project_has_tests(root):
        suggestions.append({"command": f"{python_prefix} python -m pytest -q", "reason": "workspace contains tests"})
    elif has_python:
        suggestions.append({"command": f"{python_prefix} python -m compileall .", "reason": "python files changed but no tests were detected"})
    deduped = []
    seen = set()
    for item in suggestions:
        command = item["command"]
        if command in seen:
            continue
        seen.add(command)
        deduped.append(item)
    return deduped
