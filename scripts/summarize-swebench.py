#!/usr/bin/env python3
"""Summarize Pico SWE-bench prediction output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir")
    parser.add_argument("--eval-report-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    summary = summarize(Path(args.output_dir), Path(args.eval_report_dir) if args.eval_report_dir else None)
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def summarize(output_dir: Path, eval_report_dir: Path | None = None) -> dict[str, Any]:
    run_summary = _load_json(output_dir / "summary.json", {})
    preds = _load_json(output_dir / "preds.json", {})
    result = {
        "selected_instances": run_summary.get("selected_instances"),
        "attempted_instances": run_summary.get("attempted_instances"),
        "non_empty_predictions": run_summary.get("non_empty_predictions"),
        "empty_patch_count": run_summary.get("empty_patch_count"),
        "setup_error_count": run_summary.get("setup_error_count"),
        "model_error_count": run_summary.get("model_error_count"),
        "timeout_count": run_summary.get("timeout_count"),
        "predictions_count": len(preds) if isinstance(preds, dict) else 0,
        "submitted_instances": None,
        "completed_instances": None,
        "resolved_instances": None,
        "resolved_rate": None,
    }
    if eval_report_dir:
        resolved, total, submitted, completed = _read_eval_counts(eval_report_dir)
        denominator = submitted if submitted is not None else total
        result["submitted_instances"] = submitted
        result["completed_instances"] = completed
        result["resolved_instances"] = resolved
        result["resolved_rate"] = (resolved / denominator) if resolved is not None and denominator else None
    return result


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _read_eval_counts(root: Path) -> tuple[int | None, int | None, int | None, int | None]:
    fallback = (None, None, None, None)
    for path in sorted(root.rglob("*.json")):
        payload = _load_json(path, None)
        if not isinstance(payload, dict):
            continue
        if "resolved" in payload:
            resolved = payload["resolved"]
        elif "resolved_instances" in payload:
            resolved = payload["resolved_instances"]
        else:
            resolved = None
        if "total" in payload:
            total = payload["total"]
        elif "total_instances" in payload:
            total = payload["total_instances"]
        else:
            total = None
        submitted = payload.get("submitted_instances")
        completed = payload.get("completed_instances")
        if isinstance(resolved, list):
            resolved = len(resolved)
        if isinstance(total, list):
            total = len(total)
        if isinstance(submitted, list):
            submitted = len(submitted)
        if isinstance(completed, list):
            completed = len(completed)
        if isinstance(resolved, int):
            counts = (
                resolved,
                total if isinstance(total, int) else None,
                submitted if isinstance(submitted, int) else None,
                completed if isinstance(completed, int) else None,
            )
            if counts[2] is not None:
                return counts
            if fallback == (None, None, None, None):
                fallback = counts
    return fallback


if __name__ == "__main__":
    raise SystemExit(main())
