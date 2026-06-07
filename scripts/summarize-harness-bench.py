#!/usr/bin/env python3
"""Summarize Harness-Bench JSON results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", help="Harness-Bench result JSON file or directory.")
    parser.add_argument("--output", default=None, help="Optional summary JSON path.")
    args = parser.parse_args(argv)

    summary = summarize_path(Path(args.results))
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def summarize_path(path: Path) -> dict[str, Any]:
    rows = [_row_from_payload(payload, source) for source, payload in _iter_payloads(path)]
    rows = [row for row in rows if row]
    model_ids = sorted({row["model_id"] for row in rows if row.get("model_id")})
    failed = [row["task_id"] for row in rows if not _oracle_passed(row)]
    return {
        "model_id": model_ids[0] if len(model_ids) == 1 else model_ids,
        "attempted_tasks": len(rows),
        "oracle_passed_tasks": len(rows) - len(failed),
        "oracle_failed_tasks": len(failed),
        "oracle_pass_rate": _ratio(len(rows) - len(failed), len(rows)),
        "average_outcome_score": _avg(rows, "outcome_score"),
        "average_process_score": _avg(rows, "process_score"),
        "average_combined_score": _avg(rows, "combined_score"),
        "average_total_tokens": _avg(rows, "total_tokens"),
        "failed_task_ids": failed,
        "task_rows": rows,
    }


def _iter_payloads(path: Path):
    paths = [path] if path.is_file() else sorted(path.rglob("*.json"))
    for item in paths:
        try:
            payload = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, list):
            for index, record in enumerate(payload):
                if isinstance(record, dict):
                    yield f"{item}#{index}", record
        elif isinstance(payload, dict):
            yield str(item), payload


def _row_from_payload(payload: dict[str, Any], source: str) -> dict[str, Any]:
    oracle = _dict(payload.get("oracle_result"))
    scoring = _dict(payload.get("scoring"))
    process = _dict(payload.get("process_result"))
    combined = _dict(payload.get("combined_result"))
    usage_summary = _dict(payload.get("usage_summary"))
    usage = _dict(payload.get("usage"))

    outcome_score = _first_number(
        oracle.get("outcome_score"),
        scoring.get("outcome_score"),
        combined.get("outcome_score"),
    )
    process_score = _first_number(
        process.get("total"),
        combined.get("process_score"),
        scoring.get("process_score"),
    )
    combined_score = _first_number(
        combined.get("combined_score"),
        scoring.get("combined_score"),
        outcome_score,
    )
    total_tokens = _first_number(
        usage_summary.get("total_tokens"),
        usage.get("total_tokens"),
    )
    return {
        "task_id": str(payload.get("task_id") or payload.get("task") or Path(source).stem),
        "model_id": str(payload.get("model_id") or payload.get("model") or ""),
        "outcome_score": outcome_score,
        "process_score": process_score,
        "combined_score": combined_score,
        "total_tokens": total_tokens,
        "path": source,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    return mean(values) if values else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _oracle_passed(row: dict[str, Any]) -> bool:
    score = row.get("outcome_score")
    return isinstance(score, (int, float)) and float(score) >= 1.0


if __name__ == "__main__":
    raise SystemExit(main())
