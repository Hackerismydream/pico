"""PicoBench summary JSON/Markdown generation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def build_report_card(
    *,
    suite: str,
    output_dir: str | Path,
    pico_commit: str,
    started_at: str | None,
    results: list[dict[str, Any]],
    benchmark_suite: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    total = len(results)
    strict_passed = sum(1 for result in results if result.get("strict_pass"))
    return {
        "schema_version": 1,
        "suite": suite,
        "benchmark_suite": benchmark_suite or suite,
        "provider": provider or "",
        "model": model or "",
        "pico_commit": pico_commit,
        "started_at": started_at or datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(Path(output_dir).resolve()),
        "task_count": total,
        "strict_passed": strict_passed,
        "strict_failed": total - strict_passed,
        "strict_pass_rate": _ratio(strict_passed, total),
        "functional_pass_rate": _check_group_rate(results, {"public_test", "public_pytest", "hidden_pytest", "command"}),
        "evidence_consistency_rate": _check_group_rate(results, {"report_trace_session_consistency"}),
        "safety_violation_rate": _ratio(
            sum(1 for result in results if result.get("failure_category") in {"secret_leak", "path_escape_attempt", "sandbox_failure"}),
            total,
        ),
        "avg_tool_steps": _mean(_report_number(results, "tool_steps")),
        "avg_cost_usd": _mean(_report_number(results, "cost_usd")),
        "failure_category_counts": _failure_counts(results),
        "results": results,
    }


def write_report_card(summary: dict[str, Any], output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(summary_markdown(summary), encoding="utf-8")


def summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# PicoBench Summary",
        "",
        f"- suite: {summary.get('suite', '')}",
        f"- model: {summary.get('model', '')}",
        f"- provider: {summary.get('provider', '')}",
        f"- pico_commit: {summary.get('pico_commit', '')}",
        f"- started_at: {summary.get('started_at', '')}",
        f"- output_dir: {summary.get('output_dir', '')}",
        f"- strict_pass_rate: {float(summary.get('strict_pass_rate', 0.0)):.3f}",
        f"- functional_pass_rate: {float(summary.get('functional_pass_rate', 0.0)):.3f}",
        f"- evidence_consistency_rate: {float(summary.get('evidence_consistency_rate', 0.0)):.3f}",
        f"- safety_violation_rate: {float(summary.get('safety_violation_rate', 0.0)):.3f}",
        f"- avg_tool_steps: {float(summary.get('avg_tool_steps', 0.0)):.2f}",
        f"- avg_cost_usd: {float(summary.get('avg_cost_usd', 0.0)):.4f}",
        "",
        "| Task | Category | Strict | Functional | Safety | Evidence | Failure | Evidence Path |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for result in summary.get("results", []):
        functional = _result_check_group(result, {"public_test", "public_pytest", "hidden_pytest", "command"})
        evidence = _result_check_group(result, {"report_trace_session_consistency"})
        safety = result.get("failure_category") not in {"secret_leak", "path_escape_attempt", "sandbox_failure"}
        lines.append(
            f"| {result.get('task_id', '')} | {result.get('category', '')} | {int(bool(result.get('strict_pass')))} | "
            f"{int(functional)} | {int(safety)} | {int(evidence)} | "
            f"{result.get('failure_category') or ''} | {result.get('evidence_path', '')} |"
        )
    return "\n".join(lines) + "\n"


def _check_group_rate(results: list[dict[str, Any]], names: set[str]) -> float:
    if not results:
        return 0.0
    passed = 0
    for result in results:
        if _result_check_group(result, names):
            passed += 1
    return passed / len(results)


def _result_check_group(result: dict[str, Any], names: set[str]) -> bool:
    checks = [check for check in result.get("checks", []) if check.get("name") in names]
    return bool(checks) and all(check.get("passed") for check in checks)


def _report_number(results: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for result in results:
        report = result.get("report") or {}
        if report.get(key) is not None:
            values.append(float(report[key]))
    return values


def _failure_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if result.get("strict_pass"):
            continue
        category = str(result.get("failure_category") or "unknown")
        counts[category] = counts.get(category, 0) + 1
    return counts


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
