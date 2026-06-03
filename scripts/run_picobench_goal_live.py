#!/usr/bin/env python3
"""一键运行 PicoBench DeepSeek 目标闭环。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pico.evaluation.cli_runner import _output_dir_allowed


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
    parser = ChineseArgumentParser(description="运行 100 任务 DeepSeek live、消融和最终目标审计。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出。")
    parser.add_argument("--benchmark", default="benchmarks/picobench-core-v1.yaml", help="Benchmark YAML/JSON 路径。")
    parser.add_argument("--suite", default="core", help="要运行的 suite。")
    parser.add_argument("--task", action="append", default=[], help="只运行指定任务 id；可重复传入。")
    parser.add_argument("--task-list", action="append", default=[], help="从文件读取任务 id；一行一个，支持 # 注释。")
    parser.add_argument("--output-dir", required=True, help="闭环输出目录，必须在 Pico repo 外，或 _local/benchmark/runs 下。")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--approval", default="auto", choices=("ask", "auto", "never"))
    parser.add_argument("--sandbox", default="required", choices=("off", "best_effort", "required"))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--config", default=None)
    parser.add_argument("--max-steps", type=int, default=None, help="覆盖任务 execution.max_steps。")
    parser.add_argument("--timeout-sec", type=int, default=None, help="覆盖任务 execution.timeout_sec。")
    parser.add_argument("--pico-command", default="uv run pico", help="调用 Pico 的命令。")
    parser.add_argument("--no-hidden-tests", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--discard-workspaces", action="store_true")
    parser.add_argument("--preflight-task", action="append", default=[], help="先运行少量真实 DeepSeek task；若发现 provider 余额不足则短路。")
    parser.add_argument("--preflight-output-dir", default=None, help="预检输出目录；默认 output-dir/preflight。")
    parser.add_argument("--preflight-max-steps", type=int, default=None, help="只覆盖预检任务的 execution.max_steps。")
    parser.add_argument("--preflight-timeout-sec", type=int, default=None, help="只覆盖预检任务的 execution.timeout_sec。")
    parser.add_argument("--skip-live", action="store_true", help="跳过 100 任务 live run，复用 live-output-dir。")
    parser.add_argument("--skip-ablation", action="store_true", help="跳过消融 run，复用 ablation-output-dir。")
    parser.add_argument("--live-output-dir", default=None, help="100 任务 live 输出目录；默认 output-dir/live。")
    parser.add_argument("--retry-from-output-dir", default=None, help="从旧 PicoBench 输出读取 retry_tasks.txt，并自动作为 merge source。")
    parser.add_argument("--merge-source-dir", action="append", default=[], help="合并审计前额外输入的 PicoBench 输出目录；适合旧全量 + retry 输出。")
    parser.add_argument("--merged-output-dir", default=None, help="合并后的 live 输出目录；默认 output-dir/merged-live。")
    parser.add_argument("--ablation-output-dir", default=None, help="消融输出目录；默认 output-dir/ablation。")
    parser.add_argument("--audit-output-dir", default=None, help="目标审计输出目录；默认 output-dir/audit。")
    parser.add_argument("--runner-script", default=str(ROOT / "scripts" / "run_picobench.py"), help="PicoBench runner 脚本。")
    parser.add_argument("--reclassify-script", default=str(ROOT / "scripts" / "reclassify_picobench_failures.py"), help="失败重分类脚本。")
    parser.add_argument("--merge-script", default=str(ROOT / "scripts" / "merge_picobench_summaries.py"), help="summary 合并脚本。")
    parser.add_argument("--ablation-script", default=str(ROOT / "scripts" / "run_picobench_ablation.py"), help="消融脚本。")
    parser.add_argument("--audit-script", default=str(ROOT / "scripts" / "audit_picobench_goal.py"), help="目标审计脚本。")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    _apply_retry_from_output_dir(args)
    output_dir = Path(args.output_dir).resolve()
    if not _output_dir_allowed(output_dir):
        raise SystemExit("闭环输出目录必须在 Pico repo 之外，或 _local/benchmark/runs 下。")
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    preflight_output_dir = Path(args.preflight_output_dir).resolve() if args.preflight_output_dir else output_dir / "preflight"
    live_output_dir = Path(args.live_output_dir).resolve() if args.live_output_dir else output_dir / "live"
    merged_output_dir = Path(args.merged_output_dir).resolve() if args.merged_output_dir else output_dir / "merged-live"
    ablation_output_dir = Path(args.ablation_output_dir).resolve() if args.ablation_output_dir else output_dir / "ablation"
    audit_output_dir = Path(args.audit_output_dir).resolve() if args.audit_output_dir else output_dir / "audit"

    steps: list[dict[str, Any]] = []
    if args.preflight_task and not args.skip_live:
        steps.append(_run_step("preflight", _preflight_command(args, preflight_output_dir), logs_dir))
        if _provider_blocked(preflight_output_dir):
            steps.append(_skipped_step("live", "预检已确认 provider 余额不足，跳过 100 任务 live run。", live_output_dir))
            steps.append(_skipped_step("reclassify", "预检已确认 provider 余额不足，跳过失败重分类。", live_output_dir))
            steps.append(_skipped_step("ablation", "预检已确认 provider 余额不足，跳过消融 run。", ablation_output_dir))
            manifest = _build_manifest(
                output_dir=output_dir,
                preflight_output_dir=preflight_output_dir,
                live_output_dir=live_output_dir,
                audit_live_output_dir=live_output_dir,
                merged_output_dir=merged_output_dir,
                ablation_output_dir=ablation_output_dir,
                audit_output_dir=audit_output_dir,
                steps=steps,
                status="provider_blocked",
            )
            _write_manifest(manifest, output_dir)
            print(json.dumps({"output_dir": str(output_dir), "status": manifest["status"]}, ensure_ascii=False, sort_keys=True))
            return 1

    if args.skip_live:
        steps.append(_skipped_step("live", "已跳过 100 任务 live run，复用既有输出。", live_output_dir))
    else:
        steps.append(_run_step("live", _live_command(args, live_output_dir), logs_dir))

    if (live_output_dir / "summary.json").exists():
        steps.append(_run_step("reclassify", _reclassify_command(args, live_output_dir), logs_dir))
    else:
        steps.append(_skipped_step("reclassify", "live 输出缺少 summary.json，无法做失败重分类。", live_output_dir))

    audit_live_output_dir = live_output_dir
    if args.merge_source_dir:
        merge_inputs = [Path(path).resolve() for path in args.merge_source_dir]
        if (live_output_dir / "summary.json").exists() or (live_output_dir / "summary_reclassified.json").exists():
            merge_inputs.append(live_output_dir)
        steps.append(_run_step("merge", _merge_command(args, merge_inputs, merged_output_dir), logs_dir))
        audit_live_output_dir = merged_output_dir

    if args.skip_ablation:
        steps.append(_skipped_step("ablation", "已跳过消融 run，复用既有输出。", ablation_output_dir))
    else:
        steps.append(_run_step("ablation", _ablation_command(args, ablation_output_dir), logs_dir))

    steps.append(_run_step("audit", _audit_command(args, audit_live_output_dir, ablation_output_dir, audit_output_dir), logs_dir))
    manifest = _build_manifest(
        output_dir=output_dir,
        preflight_output_dir=preflight_output_dir,
        live_output_dir=live_output_dir,
        audit_live_output_dir=audit_live_output_dir,
        merged_output_dir=merged_output_dir,
        ablation_output_dir=ablation_output_dir,
        audit_output_dir=audit_output_dir,
        steps=steps,
        status=_overall_status(steps),
    )
    _write_manifest(manifest, output_dir)
    print(json.dumps({"output_dir": str(output_dir), "status": manifest["status"]}, ensure_ascii=False, sort_keys=True))
    audit_step = next((step for step in steps if step["name"] == "audit"), {})
    return 0 if audit_step.get("returncode") == 0 else 1


def _preflight_command(args, output_dir: Path) -> list[str]:
    command = _live_command(args, output_dir)
    command = _replace_task_args(command, args.preflight_task)
    if args.preflight_max_steps is not None:
        command = _replace_optional_value_arg(command, "--max-steps", str(args.preflight_max_steps))
    if args.preflight_timeout_sec is not None:
        command = _replace_optional_value_arg(command, "--timeout-sec", str(args.preflight_timeout_sec))
    return command


def _live_command(args, output_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(Path(args.runner_script).resolve()),
        "--benchmark",
        args.benchmark,
        "--suite",
        args.suite,
        "--output-dir",
        str(output_dir),
        "--provider",
        args.provider,
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
    _append_task_args(command, args)
    _append_common_optional_args(command, args)
    return command


def _replace_task_args(command: list[str], task_ids: list[str]) -> list[str]:
    filtered: list[str] = []
    skip_next = False
    for item in command:
        if skip_next:
            skip_next = False
            continue
        if item in {"--task", "--task-list"}:
            skip_next = True
            continue
        filtered.append(item)
    for task_id in task_ids:
        filtered.extend(["--task", task_id])
    return filtered


def _replace_optional_value_arg(command: list[str], option: str, value: str) -> list[str]:
    filtered: list[str] = []
    skip_next = False
    replaced = False
    for item in command:
        if skip_next:
            filtered.append(value)
            skip_next = False
            continue
        if item == option:
            filtered.append(item)
            skip_next = True
            replaced = True
            continue
        filtered.append(item)
    if not replaced:
        filtered.extend([option, value])
    return filtered


def _reclassify_command(args, live_output_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(Path(args.reclassify_script).resolve()),
        "--input-dir",
        str(live_output_dir),
    ]


def _merge_command(args, input_dirs: list[Path], output_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(Path(args.merge_script).resolve()),
        "--output-dir",
        str(output_dir),
        "--expected-task-count",
        "100",
    ]
    for input_dir in input_dirs:
        command.extend(["--input-dir", str(input_dir)])
    return command


def _ablation_command(args, output_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(Path(args.ablation_script).resolve()),
        "--benchmark",
        args.benchmark,
        "--suite",
        args.suite,
        "--output-dir",
        str(output_dir),
        "--provider",
        args.provider,
        "--approval",
        args.approval,
        "--sandbox",
        args.sandbox,
        "--runs",
        str(args.runs),
        "--pico-command",
        args.pico_command,
    ]
    _append_task_args(command, args)
    _append_common_optional_args(command, args)
    return command


def _audit_command(args, live_output_dir: Path, ablation_output_dir: Path, audit_output_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(Path(args.audit_script).resolve()),
        "--benchmark",
        args.benchmark,
        "--live-output-dir",
        str(live_output_dir),
        "--ablation-output-dir",
        str(ablation_output_dir),
        "--output-dir",
        str(audit_output_dir),
        "--json",
    ]


def _append_common_optional_args(command: list[str], args) -> None:
    if args.model:
        command.extend(["--model", args.model])
    if args.config:
        command.extend(["--config", args.config])
    if args.max_steps is not None:
        command.extend(["--max-steps", str(args.max_steps)])
    if args.timeout_sec is not None:
        command.extend(["--timeout-sec", str(args.timeout_sec)])
    if args.no_hidden_tests:
        command.append("--no-hidden-tests")
    if args.fail_fast:
        command.append("--fail-fast")
    if args.discard_workspaces:
        command.append("--discard-workspaces")


def _append_task_args(command: list[str], args) -> None:
    for task_id in args.task:
        command.extend(["--task", task_id])
    for path in args.task_list:
        command.extend(["--task-list", path])


def _apply_retry_from_output_dir(args) -> None:
    if not args.retry_from_output_dir:
        return
    retry_source = Path(args.retry_from_output_dir).resolve()
    retry_list = retry_source / "retry_tasks.txt"
    if not retry_list.exists():
        raise SystemExit(f"找不到 retry_tasks.txt：{retry_list}")
    if not args.task and not args.task_list:
        args.task_list.append(str(retry_list))
    if str(retry_source) not in {str(Path(path).resolve()) for path in args.merge_source_dir}:
        args.merge_source_dir.append(str(retry_source))


def _run_step(name: str, command: list[str], logs_dir: Path) -> dict[str, Any]:
    started = datetime.now().isoformat(timespec="seconds")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    stdout_path = logs_dir / f"{name}.stdout.txt"
    stderr_path = logs_dir / f"{name}.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return {
        "name": name,
        "status": "completed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "command": command,
        "started_at": started,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _skipped_step(name: str, reason: str, output_dir: Path) -> dict[str, Any]:
    return {
        "name": name,
        "status": "skipped",
        "returncode": None,
        "command": [],
        "reason": reason,
        "output_dir": str(output_dir),
    }


def _overall_status(steps: list[dict[str, Any]]) -> str:
    audit_step = next((step for step in steps if step["name"] == "audit"), {})
    if audit_step.get("returncode") == 0:
        return "completed"
    audit_status = _audit_stdout_status(audit_step)
    if audit_status:
        return audit_status
    if audit_step.get("returncode") == 1:
        return "audit_failed"
    return "failed"


def _build_manifest(
    *,
    output_dir: Path,
    preflight_output_dir: Path,
    live_output_dir: Path,
    audit_live_output_dir: Path,
    merged_output_dir: Path,
    ablation_output_dir: Path,
    audit_output_dir: Path,
    steps: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(output_dir),
        "preflight_output_dir": str(preflight_output_dir),
        "live_output_dir": str(live_output_dir),
        "audit_live_output_dir": str(audit_live_output_dir),
        "merged_output_dir": str(merged_output_dir),
        "ablation_output_dir": str(ablation_output_dir),
        "audit_output_dir": str(audit_output_dir),
        "steps": steps,
        "status": status,
    }


def _write_manifest(manifest: dict[str, Any], output_dir: Path) -> None:
    (output_dir / "goal_live_run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "goal_live_run.md").write_text(_markdown(manifest), encoding="utf-8")


def _provider_blocked(output_dir: Path) -> bool:
    summary_path = output_dir / "summary_reclassified.json"
    if not summary_path.exists():
        summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    counts = summary.get("failure_category_counts") or {}
    return bool(counts.get("provider_insufficient_balance"))


def _audit_stdout_status(audit_step: dict[str, Any]) -> str:
    stdout_path = audit_step.get("stdout_path")
    if not stdout_path:
        return ""
    path = Path(stdout_path)
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    status = str(payload.get("status") or "")
    return status if status in {"provider_blocked", "incomplete", "completed"} else ""


def _markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# PicoBench DeepSeek 目标闭环运行",
        "",
        f"- 状态: {manifest['status']}",
        f"- 输出目录: {manifest['output_dir']}",
        f"- 预检输出: {manifest.get('preflight_output_dir', '')}",
        f"- Live 输出: {manifest['live_output_dir']}",
        f"- 审计使用的 live 输出: {manifest['audit_live_output_dir']}",
        f"- 消融输出: {manifest['ablation_output_dir']}",
        f"- 审计输出: {manifest['audit_output_dir']}",
        "",
        "| 步骤 | 状态 | 返回码 | 日志 |",
        "|---|---|---:|---|",
    ]
    for step in manifest["steps"]:
        logs = step.get("stdout_path", "")
        if step.get("stderr_path"):
            logs += f" / {step['stderr_path']}"
        lines.append(f"| {step['name']} | {step['status']} | {step.get('returncode')} | {logs or step.get('reason', '')} |")
    return "\n".join(lines) + "\n"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
