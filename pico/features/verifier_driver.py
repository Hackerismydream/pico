"""Derive verification pressure from runtime artifacts.

This module deliberately stays generic. It looks at files, scripts, API path
relationships, and recorded verification evidence; it does not encode product
templates such as a particular CRUD app or framework-specific smoke test.
"""

from __future__ import annotations

import re
from pathlib import Path

from .artifacts import suggest_verification_commands


def _api_pattern(path: str) -> re.Pattern:
    escaped = re.escape(str(path).strip())
    escaped = re.sub(r"\\\{[^/]+\\\}", r"[^/]+", escaped)
    return re.compile(rf"^{escaped}$")


def _route_covers_reference(route: str, reference: str) -> bool:
    route = str(route or "").strip()
    reference = str(reference or "").strip()
    if not route or not reference:
        return False
    if route == reference:
        return True
    return bool(_api_pattern(route).match(reference))


def _latest_passed_verification(verifications: list[dict] | None) -> dict | None:
    for artifact in reversed(list(verifications or [])):
        if artifact.get("status") == "passed":
            return artifact
    return None


def _requirement(req_id: str, description: str, reason: str) -> dict:
    return {"id": req_id, "description": description, "reason": reason}


def _static_check(check_id: str, status: str, summary: str, details=None) -> dict:
    return {
        "id": check_id,
        "status": status,
        "summary": summary,
        "details": list(details or []),
    }


def build_verification_plan(root, artifact_graph: dict | None, verifications: list[dict] | None = None) -> dict:
    root = Path(root)
    graph = artifact_graph or {}
    path_groups = graph.get("paths", {}) if isinstance(graph, dict) else {}
    api = graph.get("api", {}) if isinstance(graph, dict) else {}

    requirements = []
    static_checks = []
    missing_evidence = []

    backend_paths = list(path_groups.get("backend", []) or [])
    frontend_paths = list(path_groups.get("frontend", []) or [])
    test_paths = list(path_groups.get("tests", []) or [])
    dependency_paths = list(path_groups.get("dependencies", []) or [])
    docs_paths = list(path_groups.get("docs", []) or [])

    if any(str(path).endswith(".py") for path in backend_paths + test_paths) or (root / "requirements.txt").is_file():
        requirements.append(
            _requirement(
                "python_syntax_or_tests",
                "Run Python syntax or test verification",
                "python files or requirements were touched",
            )
        )
    if (root / "package.json").is_file() or any(str(path).endswith((".js", ".jsx", ".ts", ".tsx")) for path in frontend_paths):
        requirements.append(
            _requirement(
                "package_build_or_test",
                "Run package test/build verification when scripts exist",
                "frontend or package metadata was touched",
            )
        )
    if dependency_paths:
        requirements.append(
            _requirement(
                "dependency_install_or_resolution",
                "Verify dependency-aware commands still resolve",
                "dependency metadata changed",
            )
        )
    if docs_paths:
        requirements.append(
            _requirement(
                "docs_startup_consistency",
                "Check documentation does not contradict generated artifacts",
                "documentation was touched",
            )
        )

    backend_routes = list(api.get("backend_routes", []) or [])
    frontend_refs = list(api.get("frontend_references", []) or [])
    stale_artifacts = [
        str(item.get("path", ""))
        for item in list(graph.get("artifacts", []) or [])
        if str(item.get("status", "")) == "stale" and str(item.get("path", ""))
    ]
    if stale_artifacts:
        missing_evidence.append(
            {
                "requirement": "stale_artifacts",
                "reason": "files changed after the latest passed verification",
                "details": stale_artifacts,
            }
        )
    if backend_routes and frontend_refs:
        requirements.append(
            _requirement(
                "api_consistency",
                "Check frontend API references are covered by backend routes",
                "both frontend API references and backend routes were detected",
            )
        )
        uncovered = [
            ref
            for ref in frontend_refs
            if not any(_route_covers_reference(route, ref) for route in backend_routes)
        ]
        if uncovered:
            static_checks.append(
                _static_check(
                    "api_consistency",
                    "failed",
                    "some frontend API references do not match backend routes",
                    uncovered,
                )
            )
            missing_evidence.append(
                {
                    "requirement": "api_consistency",
                    "reason": "frontend API references are not covered by backend routes",
                    "details": uncovered,
                }
            )
        else:
            static_checks.append(
                _static_check(
                    "api_consistency",
                    "passed",
                    "frontend API references are covered by detected backend routes",
                    frontend_refs,
                )
            )

    suggested_commands = suggest_verification_commands(root, graph)
    latest_passed = _latest_passed_verification(verifications)
    if requirements and latest_passed is None:
        missing_evidence.append(
            {
                "requirement": "runtime_verification",
                "reason": "no passed verification artifact has been recorded",
                "details": [item["id"] for item in requirements],
            }
        )

    return {
        "schema_version": "verification-plan-v1",
        "requirements": requirements,
        "suggested_commands": suggested_commands,
        "static_checks": static_checks,
        "missing_evidence": missing_evidence,
        "latest_passed_verification": dict(latest_passed or {}),
    }


def select_verification_action(verification_plan: dict | None) -> dict:
    plan = verification_plan or {}
    missing_evidence = list(plan.get("missing_evidence", []) or [])
    failed_static_checks = [
        item for item in list(plan.get("static_checks", []) or []) if str(item.get("status", "")) == "failed"
    ]
    if not missing_evidence and not failed_static_checks:
        return {}
    for suggestion in list(plan.get("suggested_commands", []) or []):
        command = str(suggestion.get("command", "")).strip()
        if command and _is_safe_auto_verification_command(command):
            return {"name": "run_shell", "args": {"command": command, "timeout": 60}}
    return {}


def _is_safe_auto_verification_command(command: str) -> bool:
    command = " ".join(str(command or "").split())
    safe_commands = {
        "uv run python -m compileall .",
        "uv run --with-requirements requirements.txt python -m compileall .",
        "uv run python -m pytest -q",
        "uv run --with-requirements requirements.txt python -m pytest -q",
    }
    return command in safe_commands
