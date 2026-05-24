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
    skipped = sum(1 for result in results if result.get("skipped"))
    evaluated_total = total - skipped
    failure_counts = _failure_counts(results)
    durations = [float(result.get("duration_ms") or 0) for result in results if not result.get("skipped")]
    evidence_mode = _evidence_mode(results)
    evidence_consistency_rate = (
        "not_applicable"
        if evidence_mode == "delegated_human_gate"
        else _check_group_rate(_native_evidence_results(results), {"report_trace_session_consistency"})
    )
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
        "skipped": skipped,
        "strict_passed": strict_passed,
        "strict_failed": evaluated_total - strict_passed,
        "strict_pass_rate": _ratio(strict_passed, evaluated_total),
        "functional_pass_rate": _check_group_rate(results, {"public_test", "public_pytest", "hidden_pytest", "command"}),
        "evidence_mode": evidence_mode,
        "evidence_consistency_rate": evidence_consistency_rate,
        "safety_violation_rate": _ratio(
            sum(1 for result in results if result.get("failure_category") in {"secret_leak", "path_escape_attempt", "sandbox_failure"}),
            evaluated_total,
        ),
        "avg_tool_steps": _mean(_report_number(results, "tool_steps")),
        "avg_cost_usd": _mean(_report_number(results, "cost_usd")),
        "timeout_count": failure_counts.get("timeout", 0),
        "duration_ms_p50": _percentile(durations, 50),
        "duration_ms_p95": _percentile(durations, 95),
        "category_breakdown": _category_breakdown(results),
        "failure_category_counts": failure_counts,
        "failure_taxonomy_table": [
            {"failure_category": category, "count": count}
            for category, count in sorted(failure_counts.items())
        ],
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
    (output_dir / "summary_compact.json").write_text(
        json.dumps(_compact_summary(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )


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
        f"- skipped: {summary.get('skipped', 0)}",
        f"- strict_pass_rate: {float(summary.get('strict_pass_rate', 0.0)):.3f}",
        f"- functional_pass_rate: {float(summary.get('functional_pass_rate', 0.0)):.3f}",
        f"- evidence_consistency_rate: {_format_metric(summary.get('evidence_consistency_rate', 0.0))}",
        f"- safety_violation_rate: {float(summary.get('safety_violation_rate', 0.0)):.3f}",
        f"- avg_tool_steps: {float(summary.get('avg_tool_steps', 0.0)):.2f}",
        f"- avg_cost_usd: {float(summary.get('avg_cost_usd', 0.0)):.4f}",
        f"- timeout_count: {summary.get('timeout_count', 0)}",
        f"- duration_ms_p50: {float(summary.get('duration_ms_p50', 0.0)):.1f}",
        f"- duration_ms_p95: {float(summary.get('duration_ms_p95', 0.0)):.1f}",
        "",
        "## Category Breakdown",
        "",
        "| Category | Tasks | Strict Passed | Strict Failed | Strict Pass Rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, row in sorted((summary.get("category_breakdown") or {}).items()):
        lines.append(
            f"| {category} | {row['task_count']} | {row['strict_passed']} | {row['strict_failed']} | "
            f"{float(row['strict_pass_rate']):.3f} |"
        )
    lines.extend([
        "",
        "## Failures",
        "",
        "| Failure Category | Count |",
        "|---|---:|",
    ])
    for row in summary.get("failure_taxonomy_table") or []:
        lines.append(f"| {row['failure_category']} | {row['count']} |")
    lines.extend([
        "",
        "| Task | Category | Strict | Functional | Safety | Evidence | Failure | Evidence Path |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ])
    for result in summary.get("results", []):
        functional = _result_check_group(result, {"public_test", "public_pytest", "hidden_pytest", "command"})
        evidence = (
            "n/a"
            if result.get("evidence_mode") == "delegated_human_gate"
            else str(int(_result_check_group(result, {"report_trace_session_consistency"})))
        )
        safety = result.get("failure_category") not in {"secret_leak", "path_escape_attempt", "sandbox_failure"}
        lines.append(
            f"| {result.get('task_id', '')} | {result.get('category', '')} | {int(bool(result.get('strict_pass')))} | "
            f"{int(functional)} | {int(safety)} | {evidence} | "
            f"{result.get('failure_category') or ''} | {result.get('evidence_path', '')} |"
        )
    return "\n".join(lines) + "\n"


def _check_group_rate(results: list[dict[str, Any]], names: set[str]) -> float:
    evaluated = [result for result in results if not result.get("skipped")]
    if not evaluated:
        return 0.0
    passed = 0
    for result in evaluated:
        if _result_check_group(result, names):
            passed += 1
    return passed / len(evaluated)


def _native_evidence_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        result
        for result in results
        if not result.get("skipped") and result.get("evidence_mode", "native") != "delegated_human_gate"
    ]


def _evidence_mode(results: list[dict[str, Any]]) -> str:
    evaluated = [result for result in results if not result.get("skipped")]
    if evaluated and all(result.get("evidence_mode") == "delegated_human_gate" for result in evaluated):
        return "delegated_human_gate"
    if any(result.get("evidence_mode") == "delegated_human_gate" for result in evaluated):
        return "mixed"
    return "native"


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
        if result.get("skipped"):
            continue
        if result.get("strict_pass"):
            continue
        category = str(result.get("failure_category") or "unknown")
        counts[category] = counts.get(category, 0) + 1
    return counts


def _category_breakdown(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = {}
    for result in results:
        if result.get("skipped"):
            continue
        category = str(result.get("category") or "unknown")
        row = grouped.setdefault(category, {"task_count": 0, "strict_passed": 0, "strict_failed": 0})
        row["task_count"] += 1
        if result.get("strict_pass"):
            row["strict_passed"] += 1
        else:
            row["strict_failed"] += 1
    return {
        category: {
            **row,
            "strict_pass_rate": _ratio(row["strict_passed"], row["task_count"]),
        }
        for category, row in grouped.items()
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile / 100)
    return ordered[index]


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "schema_version",
        "suite",
        "benchmark_suite",
        "provider",
        "model",
        "pico_commit",
        "task_count",
        "skipped",
        "strict_passed",
        "strict_failed",
        "strict_pass_rate",
        "functional_pass_rate",
        "evidence_mode",
        "evidence_consistency_rate",
        "safety_violation_rate",
        "timeout_count",
        "duration_ms_p50",
        "duration_ms_p95",
        "category_breakdown",
        "failure_category_counts",
    ]
    return {key: summary.get(key) for key in keys}


def _format_metric(value: Any) -> str:
    if isinstance(value, str):
        return value
    return f"{float(value or 0.0):.3f}"
