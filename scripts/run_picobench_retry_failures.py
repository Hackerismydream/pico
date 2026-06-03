#!/usr/bin/env python3
"""从上一次 PicoBench 输出中选择失败任务并续跑。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pico.evaluation.benchmark_schema import load_benchmark
from pico.evaluation.cli_runner import PicoBenchRunner
from pico.evaluation.provider_failures import normalized_failure_category


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RETRY_CATEGORIES = ["provider_insufficient_balance", "provider_network_error"]


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
    parser = ChineseArgumentParser(description="从历史 summary 中选择失败任务并续跑 PicoBench。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出。")
    parser.add_argument("--previous-output-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--benchmark", default="benchmarks/picobench-core-v1.yaml")
    parser.add_argument("--suite", default=None)
    parser.add_argument(
        "--failure-category",
        action="append",
        default=[],
        help="要续跑的归一化失败类别；默认 provider_insufficient_balance 和 provider_network_error。",
    )
    parser.add_argument("--task", action="append", default=[], help="额外任务 id 过滤；可重复传入。")
    parser.add_argument("--task-list", action="append", default=[], help="从文件读取额外任务 id 过滤；一行一个，支持 # 注释。")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--approval", default="auto", choices=("ask", "auto", "never"))
    parser.add_argument("--sandbox", default="best_effort", choices=("off", "best_effort", "required"))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--config", default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--keep-workspaces", dest="keep_workspaces", action="store_true", default=True)
    parser.add_argument("--discard-workspaces", dest="keep_workspaces", action="store_false")
    parser.add_argument("--no-hidden-tests", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--pico-command", default="uv run pico")
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
    benchmark = load_benchmark(benchmark_path, repo_root=ROOT if benchmark_path.is_relative_to(ROOT) else benchmark_path.parent)
    categories = set(args.failure_category or DEFAULT_RETRY_CATEGORIES)
    task_ids = select_failed_task_ids(Path(args.previous_output_dir), categories=categories, task_filter=set(_task_ids_from_args(args)))
    payload = {"task_count": len(task_ids), "tasks": task_ids, "failure_categories": sorted(categories)}
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if task_ids else 1
    if not task_ids:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    runner = PicoBenchRunner(
        benchmark=benchmark,
        output_dir=args.output_dir,
        suite=args.suite,
        task_ids=task_ids,
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
        max_steps_override=args.max_steps,
        timeout_sec_override=args.timeout_sec,
        pico_extra_args=_pico_feature_args(args),
    )
    summary = runner.run()
    if args.json:
        print(json.dumps({key: value for key, value in summary.items() if key != "results"}, sort_keys=True))
    else:
        print(f"PicoBench 续跑结果已写入 {summary['output_dir']}")
    return 0 if summary["strict_failed"] == 0 else 1


def select_failed_task_ids(previous_output_dir: Path, *, categories: set[str], task_filter: set[str]) -> list[str]:
    summary_path = previous_output_dir / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"找不到 summary.json：{summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    task_ids: list[str] = []
    for result in summary.get("results") or []:
        task_id = str(result.get("task_id") or "")
        if not task_id or result.get("strict_pass"):
            continue
        if task_filter and task_id not in task_filter:
            continue
        category = normalized_failure_category(result)
        if category in categories:
            task_ids.append(task_id)
    return task_ids


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
