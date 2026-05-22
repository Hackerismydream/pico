#!/usr/bin/env python3
"""Check PicoBench task-suite quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pico.evaluation.benchmark_schema import Benchmark, load_benchmark
from pico.evaluation.task_quality import check_benchmark_quality


ROOT = Path(__file__).resolve().parents[1]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check PicoBench task metadata and fixture hygiene.")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--task", action="append", default=[], help="Task id to check; can be repeated.")
    parser.add_argument("--min-tasks", type=int, default=0)
    parser.add_argument("--require-hidden", action="store_true", default=True)
    parser.add_argument("--run-public-tests", action="store_true")
    parser.add_argument("--run-hidden-tests", action="store_true")
    parser.add_argument("--require-initial-failing", action="store_true")
    parser.add_argument("--json-output", default=None)
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    benchmark_path = Path(args.benchmark)
    if not benchmark_path.is_absolute():
        benchmark_path = ROOT / benchmark_path
    benchmark = load_benchmark(benchmark_path, repo_root=ROOT)
    if args.task:
        selected = set(args.task)
        benchmark = Benchmark(
            schema_version=benchmark.schema_version,
            suite=benchmark.suite,
            tasks=[task for task in benchmark.tasks if task.task_id in selected],
            raw=benchmark.raw,
        )
        if not benchmark.tasks:
            raise SystemExit(f"no selected tasks found: {', '.join(args.task)}")
    report = check_benchmark_quality(
        benchmark,
        min_tasks=args.min_tasks,
        require_hidden=args.require_hidden,
        run_public_tests=args.run_public_tests,
        run_hidden_tests=args.run_hidden_tests,
        require_initial_failing=args.require_initial_failing,
    )
    payload = report.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
