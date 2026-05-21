#!/usr/bin/env python3
"""Run PicoBench through Pico's public CLI surface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pico.evaluation.benchmark_schema import load_benchmark
from pico.evaluation.cli_runner import PicoBenchRunner


ROOT = Path(__file__).resolve().parents[1]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run PicoBench benchmark suites.")
    parser.add_argument("--suite", default=None, help="Suite to run, e.g. core or agentic.")
    parser.add_argument("--benchmark", default="benchmarks/picobench-core-v1.yaml", help="Benchmark YAML/JSON path.")
    parser.add_argument("--task", action="append", default=[], help="Task id to run; can be repeated.")
    parser.add_argument("--driver", default=None, help="Override the task driver.")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--approval", default="auto", choices=("ask", "auto", "never"))
    parser.add_argument("--sandbox", default="best_effort", choices=("off", "best_effort", "required"))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--max-steps", type=int, default=None, help="Override task execution.max_steps.")
    parser.add_argument("--timeout-sec", type=int, default=None, help="Override task execution.timeout_sec.")
    parser.add_argument("--keep-workspaces", dest="keep_workspaces", action="store_true", default=True)
    parser.add_argument("--discard-workspaces", dest="keep_workspaces", action="store_false")
    parser.add_argument("--no-hidden-tests", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout.")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--seed", default=None, help="Reserved for deterministic task sampling.")
    parser.add_argument("--pico-command", default="uv run pico", help="Command used to invoke Pico.")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    benchmark_path = Path(args.benchmark)
    if not benchmark_path.is_absolute():
        benchmark_path = ROOT / benchmark_path
    try:
        benchmark = load_benchmark(benchmark_path, repo_root=ROOT if benchmark_path.is_relative_to(ROOT) else benchmark_path.parent)
    except ValueError as exc:
        if benchmark_path.name == "picobench-runtime-v1.json":
            print(
                "benchmarks/picobench-runtime-v1.json uses the L0 deterministic runtime schema; "
                "run scripts/run_picobench_runtime.py for that benchmark.",
                file=sys.stderr,
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2
    runner = PicoBenchRunner(
        benchmark=benchmark,
        output_dir=args.output_dir,
        suite=args.suite,
        task_ids=args.task,
        pico_command=args.pico_command,
        provider=args.provider,
        model=args.model,
        approval=args.approval,
        sandbox=args.sandbox,
        config=args.config,
        runs=args.runs,
        no_hidden_tests=args.no_hidden_tests,
        fail_fast=args.fail_fast,
        keep_workspaces=args.keep_workspaces,
        driver_override=args.driver,
        max_steps_override=args.max_steps,
        timeout_sec_override=args.timeout_sec,
    )
    summary = runner.run()
    if args.json:
        print(json.dumps({key: value for key, value in summary.items() if key != "results"}, sort_keys=True))
    else:
        print(f"PicoBench wrote {summary['output_dir']}")
    return 0 if summary["strict_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
