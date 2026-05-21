#!/usr/bin/env python3
"""Run the L0 PicoBench runtime regression through the legacy evaluator schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pico.evaluation.evaluator import run_fixed_benchmark


ROOT = Path(__file__).resolve().parents[1]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run PicoBench L0 deterministic runtime regression.")
    parser.add_argument("--benchmark", default="benchmarks/picobench-runtime-v1.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--json", action="store_true", help="Print compact artifact summary to stdout.")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    benchmark_path = Path(args.benchmark)
    if not benchmark_path.is_absolute():
        benchmark_path = ROOT / benchmark_path
    output_dir = Path(args.output_dir).resolve()
    artifact_path = output_dir / "runtime_artifact.json"
    workspace_root = output_dir / "workspaces"
    artifact = run_fixed_benchmark(
        benchmark_path=benchmark_path,
        artifact_path=artifact_path,
        workspace_root=workspace_root,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "artifact_path": str(artifact_path),
                    "benchmark": str(benchmark_path),
                    "summary": artifact["summary"],
                },
                sort_keys=True,
            )
        )
    else:
        print(f"PicoBench L0 runtime artifact wrote {artifact_path}")
    return 0 if artifact["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
