"""Consistency checks for Pico run trace, report, and task state artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .validators import CheckResult


def load_trace(trace_path: str | Path) -> list[dict[str, Any]]:
    path = Path(trace_path)
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
        if isinstance(event, dict):
            events.append(event)
    return events


def summarize_trace(events: list[dict[str, Any]]) -> dict[str, Any]:
    tool_name_counts: dict[str, int] = {}
    tool_status_counts: dict[str, int] = {}
    security_event_counts: dict[str, int] = {}
    permission_decisions: dict[str, int] = {}
    policy_decisions: dict[str, int] = {}
    artifact_paths: list[str] = []
    changed_paths: list[str] = []
    status = ""
    stop_reason = ""

    for event in events:
        event_name = str(event.get("event") or "")
        if event_name == "tool_executed":
            tool_name = _event_tool_name(event)
            if tool_name:
                tool_name_counts[tool_name] = tool_name_counts.get(tool_name, 0) + 1
            tool_status = str(event.get("tool_status") or event.get("status") or "").strip()
            if tool_status:
                tool_status_counts[tool_status] = tool_status_counts.get(tool_status, 0) + 1
            security_event = str(event.get("security_event_type") or "").strip()
            if security_event:
                security_event_counts[security_event] = security_event_counts.get(security_event, 0) + 1
            artifact = str(event.get("full_output_artifact") or event.get("artifact_path") or "").strip()
            if artifact:
                artifact_paths.append(artifact)
            for path in event.get("changed_paths") or []:
                changed_paths.append(str(path))
        if event_name == "permission_decision":
            decision = str(event.get("decision") or event.get("result") or "").strip()
            if decision:
                permission_decisions[decision] = permission_decisions.get(decision, 0) + 1
        if event_name == "tool_policy_decision":
            decision = str(event.get("decision") or event.get("result") or "").strip()
            if decision:
                policy_decisions[decision] = policy_decisions.get(decision, 0) + 1
        if event_name == "run_finished":
            status = str(event.get("status") or status or "").strip()
            stop_reason = str(event.get("stop_reason") or stop_reason or "").strip()
            for path in event.get("changed_paths") or []:
                changed_paths.append(str(path))

    return {
        "status": status,
        "stop_reason": stop_reason,
        "tool_steps": sum(tool_name_counts.values()),
        "tool_name_counts": tool_name_counts,
        "tool_status_counts": tool_status_counts,
        "security_event_counts": security_event_counts,
        "permission_decisions": permission_decisions,
        "policy_decisions": policy_decisions,
        "artifact_paths": list(dict.fromkeys(artifact_paths)),
        "changed_paths": list(dict.fromkeys(changed_paths)),
    }


def compare_report_to_trace(report: dict[str, Any], trace_summary: dict[str, Any]) -> list[CheckResult]:
    checks = [
        _match("report_status_match_trace", report.get("status"), trace_summary.get("status")),
        _match("report_stop_reason_match_trace", report.get("stop_reason"), trace_summary.get("stop_reason")),
        _match("report_tool_steps_match_trace", report.get("tool_steps"), trace_summary.get("tool_steps")),
    ]
    for key, name in [
        ("tool_name_counts", "report_tool_name_counts_match_trace"),
        ("tool_status_counts", "report_tool_status_counts_match_trace"),
        ("security_event_counts", "report_security_event_counts_match_trace"),
    ]:
        if key in report:
            checks.append(_match(name, _mapping(report, key), _mapping(trace_summary, key)))
    return checks


def compare_task_state_to_report(task_state: dict[str, Any], report: dict[str, Any]) -> list[CheckResult]:
    return [
        _match("task_state_status_match_report", task_state.get("status"), report.get("status")),
        _match("task_state_stop_reason_match_report", task_state.get("stop_reason"), report.get("stop_reason")),
    ]


def _event_tool_name(event: dict[str, Any]) -> str:
    return str(event.get("name") or event.get("tool_name") or event.get("tool") or "").strip()


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    return dict(value) if isinstance(value, dict) else {}


def _match(name: str, actual: Any, expected: Any) -> CheckResult:
    passed = actual == expected
    return CheckResult(
        name=name,
        passed=passed,
        message="" if passed else f"actual={actual!r} expected={expected!r}",
        details={"actual": actual, "expected": expected},
    )
