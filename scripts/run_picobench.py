#!/usr/bin/env python3
"""通过 Pico 公开 CLI 运行 PicoBench。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pico.evaluation.benchmark_schema import load_benchmark
from pico.evaluation.cli_runner import PicoBenchRunner


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
    parser = ChineseArgumentParser(description="运行 PicoBench benchmark suite。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出。")
    parser.add_argument("--suite", default=None, help="要运行的 suite，例如 core 或 agentic。")
    parser.add_argument("--benchmark", default="benchmarks/picobench-core-v1.yaml", help="Benchmark YAML/JSON 路径。")
    parser.add_argument("--task", action="append", default=[], help="只运行指定任务 id；可重复传入。")
    parser.add_argument("--task-list", action="append", default=[], help="从文件读取任务 id；一行一个，支持 # 注释。")
    parser.add_argument("--driver", default=None, help="覆盖任务 driver。")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--approval", default="auto", choices=("ask", "auto", "never"))
    parser.add_argument("--sandbox", default="best_effort", choices=("off", "best_effort", "required"))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--max-steps", type=int, default=None, help="覆盖任务 execution.max_steps。")
    parser.add_argument("--timeout-sec", type=int, default=None, help="覆盖任务 execution.timeout_sec。")
    parser.add_argument("--keep-workspaces", dest="keep_workspaces", action="store_true", default=True)
    parser.add_argument("--discard-workspaces", dest="keep_workspaces", action="store_false")
    parser.add_argument("--no-hidden-tests", action="store_true")
    parser.add_argument("--json", action="store_true", help="把 summary JSON 打印到 stdout。")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--seed", default=None, help="保留字段，用于未来的确定性任务采样。")
    parser.add_argument("--pico-command", default="uv run pico", help="调用 Pico 的命令。")
    parser.add_argument("--disable-memory", action="store_true", help="向 Pico 传入 --disable-memory。")
    parser.add_argument("--disable-plan-mode", action="store_true", help="向 Pico 传入 --disable-plan-mode。")
    parser.add_argument("--disable-subagents", action="store_true", help="向 Pico 传入 --disable-subagents。")
    parser.add_argument("--disable-skills", action="store_true", help="向 Pico 传入 --disable-skills。")
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
                "benchmarks/picobench-runtime-v1.json 使用 L0 deterministic runtime schema；"
                "请用 scripts/run_picobench_runtime.py 运行这个 benchmark。",
                file=sys.stderr,
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2
    runner = PicoBenchRunner(
        benchmark=benchmark,
        output_dir=args.output_dir,
        suite=args.suite,
        task_ids=_task_ids_from_args(args),
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
        pico_extra_args=_pico_feature_args(args),
    )
    summary = runner.run()
    if args.json:
        print(json.dumps({key: value for key, value in summary.items() if key != "results"}, sort_keys=True))
    else:
        print(f"PicoBench 结果已写入 {summary['output_dir']}")
    return 0 if summary["strict_failed"] == 0 else 1


def _pico_feature_args(args) -> list[str]:
    flags = []
    for attr, flag in [
        ("disable_memory", "--disable-memory"),
        ("disable_plan_mode", "--disable-plan-mode"),
        ("disable_subagents", "--disable-subagents"),
        ("disable_skills", "--disable-skills"),
    ]:
        if getattr(args, attr, False):
            flags.append(flag)
    return flags


def _task_ids_from_args(args) -> list[str]:
    task_ids = list(args.task)
    for path in args.task_list:
        task_ids.extend(_read_task_list(Path(path)))
    return _dedupe(task_ids)


def _read_task_list(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"找不到任务列表：{path}")
    task_ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.split("#", 1)[0].strip()
        if item:
            task_ids.append(item)
    return task_ids


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


if __name__ == "__main__":
    raise SystemExit(main())
