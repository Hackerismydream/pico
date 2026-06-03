#!/usr/bin/env python3
"""合并多个 PicoBench summary，后面的输出覆盖前面的同名任务。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pico.evaluation.report_card import build_report_card, write_report_card


class ChineseArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法:")

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(description="合并 PicoBench 输出目录里的 summary。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出。")
    parser.add_argument("--input-dir", action="append", required=True, help="输入输出目录；后传入的目录覆盖先传入的同名任务。")
    parser.add_argument("--output-dir", required=True, help="合并后的输出目录。")
    parser.add_argument("--expected-task-count", type=int, default=None, help="期望合并后的任务数；不匹配时返回非 0。")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    input_dirs = [Path(path).resolve() for path in args.input_dir]
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary, merge_manifest = merge_summaries(input_dirs=input_dirs, output_dir=output_dir)
    summary["merge_manifest"] = merge_manifest
    write_report_card(summary, output_dir)
    (output_dir / "merge_manifest.json").write_text(
        json.dumps(merge_manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    payload = {
        "output_dir": str(output_dir),
        "task_count": summary["task_count"],
        "strict_failed": summary["strict_failed"],
        "failure_category_counts": summary["failure_category_counts"],
        "replaced_task_count": merge_manifest["replaced_task_count"],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if args.expected_task_count is not None and summary["task_count"] != args.expected_task_count:
        return 1
    return 0 if summary["strict_failed"] == 0 else 1


def merge_summaries(*, input_dirs: list[Path], output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not input_dirs:
        raise SystemExit("至少需要一个 --input-dir。")
    task_order: list[str] = []
    task_results: dict[str, dict[str, Any]] = {}
    task_sources: dict[str, str] = {}
    replaced_tasks: set[str] = set()
    source_rows = []
    metadata_source: dict[str, Any] = {}
    for input_dir in input_dirs:
        summary_path = _summary_path(input_dir)
        if summary_path is None:
            raise SystemExit(f"找不到 summary.json 或 summary_reclassified.json：{input_dir}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not metadata_source:
            metadata_source = summary
        results = summary.get("results") or []
        source_rows.append(
            {
                "input_dir": str(input_dir),
                "summary_path": str(summary_path),
                "task_count": len(results),
                "strict_failed": summary.get("strict_failed"),
                "failure_category_counts": summary.get("failure_category_counts") or {},
            }
        )
        for result in results:
            task_id = str(result.get("task_id") or "")
            if not task_id:
                continue
            if task_id not in task_results:
                task_order.append(task_id)
            else:
                replaced_tasks.add(task_id)
            task_results[task_id] = result
            task_sources[task_id] = str(summary_path)
    merged_results = [task_results[task_id] for task_id in task_order if task_id in task_results]
    summary = build_report_card(
        suite=str(metadata_source.get("suite") or ""),
        benchmark_suite=str(metadata_source.get("benchmark_suite") or metadata_source.get("suite") or ""),
        provider=str(metadata_source.get("provider") or ""),
        model=str(metadata_source.get("model") or ""),
        output_dir=output_dir,
        pico_commit=str(metadata_source.get("pico_commit") or ""),
        started_at=datetime.now().isoformat(timespec="seconds"),
        results=merged_results,
    )
    merge_manifest = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sources": source_rows,
        "task_sources": task_sources,
        "replaced_tasks": sorted(replaced_tasks),
        "replaced_task_count": len(replaced_tasks),
        "task_count": len(merged_results),
    }
    return summary, merge_manifest


def _summary_path(input_dir: Path) -> Path | None:
    reclassified = input_dir / "summary_reclassified.json"
    if reclassified.exists():
        return reclassified
    summary = input_dir / "summary.json"
    if summary.exists():
        return summary
    return None


if __name__ == "__main__":
    raise SystemExit(main())
