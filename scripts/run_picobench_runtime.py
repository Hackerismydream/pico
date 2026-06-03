#!/usr/bin/env python3
"""通过旧 evaluator schema 运行 PicoBench L0 runtime 回归。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pico.evaluation.evaluator import run_fixed_benchmark


ROOT = Path(__file__).resolve().parents[1]


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
    parser = ChineseArgumentParser(description="运行 PicoBench L0 deterministic runtime 回归。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出。")
    parser.add_argument("--benchmark", default="benchmarks/picobench-runtime-v1.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--json", action="store_true", help="把紧凑 artifact summary 打印到 stdout。")
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
        print(f"PicoBench L0 runtime artifact 已写入 {artifact_path}")
    return 0 if artifact["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
