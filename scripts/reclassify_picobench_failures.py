#!/usr/bin/env python3
"""对旧 PicoBench summary 做 evidence-based 失败重分类。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pico.evaluation.provider_failures import normalized_failure_category
from pico.evaluation.report_card import build_report_card, summary_markdown


DEFAULT_RETRY_CATEGORIES = ["provider_insufficient_balance", "provider_network_error"]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="读取历史 PicoBench summary，并把 provider 失败从普通 model_error 中分离出来。")
    parser.add_argument("--input-dir", required=True, help="包含 summary.json 的历史 PicoBench 输出目录。")
    parser.add_argument("--output-dir", default=None, help="重分类输出目录；默认写回 input-dir，但不覆盖原 summary。")
    parser.add_argument("--retry-category", action="append", default=[], help="写入 retry_tasks.txt 的失败类别；默认 provider_insufficient_balance 和 provider_network_error。")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = input_dir / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"找不到 summary.json：{summary_path}")

    original = json.loads(summary_path.read_text(encoding="utf-8"))
    reclassified_results, reclassification_counts = reclassify_results(original.get("results") or [])
    summary = build_report_card(
        suite=str(original.get("suite") or ""),
        benchmark_suite=str(original.get("benchmark_suite") or original.get("suite") or ""),
        provider=str(original.get("provider") or ""),
        model=str(original.get("model") or ""),
        output_dir=output_dir,
        pico_commit=str(original.get("pico_commit") or ""),
        started_at=str(original.get("started_at") or ""),
        results=reclassified_results,
    )
    summary["reclassified_from"] = str(summary_path.resolve())
    summary["reclassification_counts"] = reclassification_counts

    (output_dir / "summary_reclassified.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "summary_reclassified.md").write_text(summary_markdown(summary), encoding="utf-8")

    retry_categories = set(args.retry_category or DEFAULT_RETRY_CATEGORIES)
    retry_tasks = [
        str(result.get("task_id"))
        for result in reclassified_results
        if result.get("task_id") and not result.get("strict_pass") and result.get("failure_category") in retry_categories
    ]
    (output_dir / "retry_tasks.txt").write_text("\n".join(retry_tasks) + ("\n" if retry_tasks else ""), encoding="utf-8")

    payload = {
        "output_dir": str(output_dir.resolve()),
        "retry_categories": sorted(retry_categories),
        "retry_task_count": len(retry_tasks),
        "retry_tasks": retry_tasks,
        "failure_category_counts": summary["failure_category_counts"],
        "reclassification_counts": reclassification_counts,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def reclassify_results(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    reclassified: list[dict[str, Any]] = []
    changes: dict[str, int] = {}
    for result in results:
        row = dict(result)
        old_category = str(row.get("failure_category") or "")
        new_category = normalized_failure_category(row)
        if new_category and new_category != old_category:
            changes[f"{old_category or 'unknown'}->{new_category}"] = changes.get(f"{old_category or 'unknown'}->{new_category}", 0) + 1
            row["failure_category"] = new_category
        reclassified.append(row)
    return reclassified, changes


if __name__ == "__main__":
    raise SystemExit(main())
