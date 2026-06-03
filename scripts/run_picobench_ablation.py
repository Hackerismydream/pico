#!/usr/bin/env python3
"""准备或运行 PicoBench 消融实验。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

VARIANTS = [
    ("pico-full", []),
    ("pico-no-memory", ["--disable-memory"]),
    ("pico-no-plan", ["--disable-plan-mode"]),
    ("pico-no-subagent", ["--disable-subagents"]),
    ("pico-no-skills", ["--disable-skills"]),
]


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
    parser = ChineseArgumentParser(description="规划或运行 PicoBench 消融实验。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出。")
    parser.add_argument("--benchmark", required=True, help="Benchmark YAML/JSON 路径。")
    parser.add_argument("--suite", default="core", help="要运行的 suite，例如 core 或 agentic。")
    parser.add_argument("--task", action="append", default=[], help="只运行指定任务 id；可重复传入。")
    parser.add_argument("--task-list", action="append", default=[], help="从文件读取任务 id；一行一个，支持 # 注释。")
    parser.add_argument("--driver", default=None, help="覆盖任务 driver。")
    parser.add_argument("--output-dir", required=True, help="消融汇总输出目录，必须在 Pico repo 外。")
    parser.add_argument("--plan-only", action="store_true", help="只写出消融计划，不实际调用 PicoBench。")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--approval", default="auto", choices=("ask", "auto", "never"))
    parser.add_argument("--sandbox", default="best_effort", choices=("off", "best_effort", "required"))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--config", default=None)
    parser.add_argument("--max-steps", type=int, default=None, help="覆盖任务 execution.max_steps。")
    parser.add_argument("--timeout-sec", type=int, default=None, help="覆盖任务 execution.timeout_sec。")
    parser.add_argument("--keep-workspaces", dest="keep_workspaces", action="store_true", default=True)
    parser.add_argument("--discard-workspaces", dest="keep_workspaces", action="store_false")
    parser.add_argument("--no-hidden-tests", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--seed", default=None, help="保留字段，用于未来的确定性任务采样。")
    parser.add_argument("--pico-command", default="uv run pico", help="调用 Pico 的命令。")
    parser.add_argument("--runner-script", default=str(ROOT / "scripts" / "run_picobench.py"), help="PicoBench runner 脚本路径。")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    if _is_relative_to(output_dir, ROOT):
        raise SystemExit("消融输出目录必须在 Pico repo 之外，否则 runner 会污染被测工作区。")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_dir / "runs"
    logs_dir = output_dir / "ablation_logs"
    if not args.plan_only:
        runs_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
    variants = [_plan_variant(args, output_dir, variant, pico_args) for variant, pico_args in VARIANTS]
    if not args.plan_only:
        variants = [_run_variant(args, row, logs_dir) for row in variants]
    summary = {
        "schema_version": 1,
        "benchmark": args.benchmark,
        "suite": args.suite,
        "provider": args.provider or "",
        "model": args.model or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "plan-only" if args.plan_only else "run",
        "planned_only": bool(args.plan_only),
        "variant_count": len(variants),
        "variants": variants,
    }
    (output_dir / "ablation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "ablation_summary.md").write_text(_markdown(summary), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "variant_count": len(VARIANTS), "status": summary["mode"]}, ensure_ascii=False, sort_keys=True))
    if args.plan_only:
        return 0
    return 0 if all(row["status"] == "completed" for row in variants) else 1


def _plan_variant(args, output_dir: Path, variant: str, pico_args: list[str]) -> dict:
    variant_output_dir = output_dir / "runs" / variant
    command = _runner_command(args, variant_output_dir, pico_args)
    return {
        "variant": variant,
        "status": "planned" if args.plan_only else "queued",
        "status_label": "已规划" if args.plan_only else "待运行",
        "reason": "已接入公开 CLI 功能开关，可用同一 PicoBench 运行器运行。",
        "pico_args": pico_args,
        "output_dir": str(variant_output_dir),
        "summary_path": str(variant_output_dir / "summary.json"),
        "command": command,
        "metrics": _empty_metrics(),
    }


def _run_variant(args, row: dict, logs_dir: Path) -> dict:
    variant = row["variant"]
    stdout_path = logs_dir / f"{variant}.stdout.txt"
    stderr_path = logs_dir / f"{variant}.stderr.txt"
    started = datetime.now().isoformat(timespec="seconds")
    completed = subprocess.run(
        row["command"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    summary = _read_json(Path(row["summary_path"]))
    row.update(
        {
            "started_at": started,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "returncode": completed.returncode,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "metrics": _metrics_from_summary(summary),
        }
    )
    row["status"], row["status_label"], row["reason"] = _status_from_run(completed.returncode, summary)
    return row


def _runner_command(args, output_dir: Path, pico_args: list[str]) -> list[str]:
    command = [
        sys.executable,
        str(Path(args.runner_script).resolve()),
        "--benchmark",
        args.benchmark,
        "--suite",
        args.suite,
        "--output-dir",
        str(output_dir),
        "--approval",
        args.approval,
        "--sandbox",
        args.sandbox,
        "--runs",
        str(args.runs),
        "--pico-command",
        args.pico_command,
        "--json",
    ]
    for task_id in _task_ids_from_args(args):
        command.extend(["--task", task_id])
    if args.driver:
        command.extend(["--driver", args.driver])
    if args.provider:
        command.extend(["--provider", args.provider])
    if args.model:
        command.extend(["--model", args.model])
    if args.config:
        command.extend(["--config", args.config])
    if args.max_steps is not None:
        command.extend(["--max-steps", str(args.max_steps)])
    if args.timeout_sec is not None:
        command.extend(["--timeout-sec", str(args.timeout_sec)])
    if not args.keep_workspaces:
        command.append("--discard-workspaces")
    if args.no_hidden_tests:
        command.append("--no-hidden-tests")
    if args.fail_fast:
        command.append("--fail-fast")
    if args.seed:
        command.extend(["--seed", args.seed])
    command.extend(pico_args)
    return command


def _empty_metrics() -> dict:
    return {
        "solve@1_strict": None,
        "solve@3_strict": None,
        "functional_pass_rate": None,
        "safety_violation_rate": None,
        "evidence_consistency_rate": None,
        "avg_tool_steps": None,
        "avg_cost_usd": None,
        "avg_wall_time_ms": None,
        "failure_category_counts": {},
    }


def _metrics_from_summary(summary: dict) -> dict:
    if not summary:
        return _empty_metrics()
    runs = max(1, int(summary.get("task_count") or 0))
    duration_p50 = summary.get("duration_ms_p50")
    return {
        "solve@1_strict": summary.get("strict_pass_rate"),
        "solve@3_strict": summary.get("strict_pass_rate") if runs >= 3 else None,
        "functional_pass_rate": summary.get("functional_pass_rate"),
        "safety_violation_rate": summary.get("safety_violation_rate"),
        "evidence_consistency_rate": summary.get("evidence_consistency_rate"),
        "avg_tool_steps": summary.get("avg_tool_steps"),
        "avg_cost_usd": summary.get("avg_cost_usd"),
        "avg_wall_time_ms": duration_p50,
        "failure_category_counts": summary.get("failure_category_counts") or {},
    }


def _status_from_run(returncode: int, summary: dict) -> tuple[str, str, str]:
    failure_counts = summary.get("failure_category_counts") if isinstance(summary, dict) else {}
    if returncode == 0 and summary and int(summary.get("strict_failed") or 0) == 0:
        return "completed", "已完成", "该变体的 PicoBench strict 结果全部通过。"
    if failure_counts and set(failure_counts) == {"provider_insufficient_balance"}:
        return "provider_blocked", "Provider 余额不足", "PicoBench 已运行，但模型服务商返回余额不足，无法得到模型能力结论。"
    if summary:
        return "failed", "未通过", "PicoBench 已运行，但存在 strict 失败任务。"
    return "runner_failed", "Runner 失败", "PicoBench 运行器未写出 summary.json；请查看 stderr 日志。"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _markdown(summary: dict) -> str:
    lines = [
        "# PicoBench 消融汇总",
        "",
        f"- 套件: {summary['suite']}",
        f"- 基准文件: {summary['benchmark']}",
        f"- 模式: {_mode_label(summary['mode'])}",
        f"- 模型服务商: {summary.get('provider', '')}",
        f"- 模型: {summary.get('model', '')}",
        "",
        "| 变体 | 状态 | Pico 参数 | 严格通过率 | 失败分类 | 说明 |",
        "|---|---|---|---:|---|---|",
    ]
    for row in summary["variants"]:
        metrics = row.get("metrics") or {}
        pass_rate = metrics.get("solve@1_strict")
        pass_rate_text = "无" if pass_rate is None else f"{float(pass_rate):.3f}"
        failures = json.dumps(metrics.get("failure_category_counts") or {}, ensure_ascii=False, sort_keys=True)
        pico_args = " ".join(row["pico_args"]) or "无"
        lines.append(
            f"| {row['variant']} | {row.get('status_label', row['status'])} | `{pico_args}` | "
            f"{pass_rate_text} | `{failures}` | {row['reason']} |"
        )
    return "\n".join(lines) + "\n"


def _mode_label(mode: str) -> str:
    return {"plan-only": "只生成计划", "run": "实际运行"}.get(mode, mode)


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


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
