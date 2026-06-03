#!/usr/bin/env python3
"""审计当前分支是否满足 PicoBench DeepSeek 目标。"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pico.evaluation.benchmark_schema import load_benchmark


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmarks" / "picobench-core-v1.yaml"
DEFAULT_LIVE_OUTPUT = Path("/tmp/picobench-v04-core100-deepseek-full")
DEFAULT_ABLATION_OUTPUT = Path("/tmp/picobench-v04-ablation-deepseek-balance-check")


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
    parser = ChineseArgumentParser(description="审计 PicoBench 100 个 DeepSeek live 任务的完成度。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出。")
    parser.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK), help="PicoBench core benchmark 路径。")
    parser.add_argument("--live-output-dir", default=str(DEFAULT_LIVE_OUTPUT), help="100 任务 DeepSeek live 输出目录。")
    parser.add_argument("--ablation-output-dir", default=str(DEFAULT_ABLATION_OUTPUT), help="DeepSeek 消融 smoke 输出目录。")
    parser.add_argument("--expected-branch", default="pico-learning-harness", help="期望所在分支。")
    parser.add_argument("--output-dir", required=True, help="审计报告输出目录。")
    parser.add_argument("--json", action="store_true", help="把紧凑审计结果打印到 stdout。")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = build_audit(
        benchmark_path=Path(args.benchmark),
        live_output_dir=Path(args.live_output_dir),
        ablation_output_dir=Path(args.ablation_output_dir),
        expected_branch=args.expected_branch,
    )
    (output_dir / "goal_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "goal_audit.md").write_text(render_markdown(audit), encoding="utf-8")
    compact = {
        "status": audit["status"],
        "completed": audit["completed"],
        "blocking_reason": audit["blocking_reason"],
        "output_dir": str(output_dir),
    }
    if args.json:
        print(json.dumps(compact, ensure_ascii=False, sort_keys=True))
    else:
        print(f"PicoBench 目标审计已写入 {output_dir}")
    return 0 if audit["completed"] else 1


def build_audit(
    *,
    benchmark_path: Path,
    live_output_dir: Path,
    ablation_output_dir: Path,
    expected_branch: str,
) -> dict[str, Any]:
    benchmark_path = benchmark_path.resolve()
    live_output_dir = live_output_dir.resolve()
    ablation_output_dir = ablation_output_dir.resolve()
    branch = _git_value(["branch", "--show-current"])
    benchmark = load_benchmark(benchmark_path, repo_root=ROOT if _is_relative_to(benchmark_path, ROOT) else benchmark_path.parent)
    benchmark_row = _benchmark_requirement(benchmark)
    expected_task_ids = [task.task_id for task in benchmark.tasks]
    branch_row = _requirement(
        "branch",
        branch == expected_branch,
        "当前分支符合目标分支要求。",
        f"当前分支是 `{branch}`，期望 `{expected_branch}`。",
        {"current_branch": branch, "expected_branch": expected_branch},
    )
    live_row = _live_requirement(live_output_dir, expected_task_ids=expected_task_ids)
    ablation_row = _ablation_requirement(ablation_output_dir)
    requirements = [branch_row, benchmark_row, live_row, ablation_row]
    completed = all(row["status"] == "completed" for row in requirements)
    provider_blocked = any(row["status"] == "provider_blocked" for row in requirements)
    status = "completed" if completed else ("provider_blocked" if provider_blocked else "incomplete")
    blocking_reason = ""
    if provider_blocked:
        blocking_reason = _provider_blocking_reason(requirements)
        if _has_non_provider_failures(requirements):
            blocking_reason += "；旧 live 输出仍包含非 provider 失败，provider 恢复后必须重跑验证修复"
    elif not completed:
        blocking_reason = "仍有未满足的完成条件"
    return {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "completed": completed,
        "blocking_reason": blocking_reason,
        "benchmark_path": str(benchmark_path),
        "live_output_dir": str(live_output_dir),
        "ablation_output_dir": str(ablation_output_dir),
        "requirements": requirements,
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# PicoBench DeepSeek 目标审计",
        "",
        f"- 状态: {audit['status']}",
        f"- 完成: {'是' if audit['completed'] else '否'}",
        f"- 阻塞原因: {audit.get('blocking_reason') or '无'}",
        f"- Benchmark: {audit['benchmark_path']}",
        f"- DeepSeek live 输出: {audit['live_output_dir']}",
        f"- 消融输出: {audit['ablation_output_dir']}",
        "",
        "| 条件 | 状态 | 证据 |",
        "|---|---|---|",
    ]
    for row in audit["requirements"]:
        lines.append(f"| {row['title']} | {row['status_label']} | {row['evidence']} |")
    return "\n".join(lines) + "\n"


def _benchmark_requirement(benchmark) -> dict[str, Any]:
    tasks = benchmark.tasks
    task_ids = [task.task_id for task in tasks]
    details = {
        "task_count": len(tasks),
        "unique_task_count": len(set(task_ids)),
        "hidden_fixture_count": sum(1 for task in tasks if task.hidden_fixture_path and task.hidden_fixture_path.exists()),
        "drivers": sorted({task.driver for task in tasks}),
        "first_task": task_ids[0] if task_ids else "",
        "last_task": task_ids[-1] if task_ids else "",
    }
    passed = (
        details["task_count"] == 100
        and details["unique_task_count"] == 100
        and details["hidden_fixture_count"] == 100
        and details["drivers"] == ["one_shot_cli"]
        and details["first_task"] == "core_001"
        and details["last_task"] == "core_100"
    )
    return _requirement(
        "benchmark_core_100",
        passed,
        "core benchmark 当前包含 100 个 one_shot_cli 任务，且每个任务都有 hidden fixture。",
        "core benchmark 未满足 100 个可用任务的结构要求。",
        details,
    )


def _live_requirement(live_output_dir: Path, *, expected_task_ids: list[str]) -> dict[str, Any]:
    summary_path = live_output_dir / "summary_reclassified.json"
    if not summary_path.exists():
        summary_path = live_output_dir / "summary.json"
    if not summary_path.exists():
        return _requirement(
            "deepseek_live_100",
            False,
            "",
            f"找不到 DeepSeek live summary：{summary_path}",
            {"summary_path": str(summary_path)},
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    results = summary.get("results") or []
    task_ids = {str(result.get("task_id") or "") for result in results if result.get("task_id")}
    expected_task_set = set(expected_task_ids)
    missing_expected_task_ids = sorted(expected_task_set - task_ids)
    unexpected_task_ids = sorted(task_ids - expected_task_set)
    failure_counts = summary.get("failure_category_counts") or {}
    provider = str(summary.get("provider") or "")
    merge_details = _merge_details(live_output_dir)
    deepseek_command_tasks = sorted(
        str(result.get("task_id") or "")
        for result in results
        if result.get("task_id") and _result_uses_deepseek_command(result)
    )
    missing_deepseek_command_tasks = sorted(task_id for task_id in task_ids if task_id not in set(deepseek_command_tasks))
    details = {
        "summary_path": str(summary_path),
        "provider": provider,
        "task_count": summary.get("task_count"),
        "result_count": len(results),
        "unique_task_count": len(task_ids),
        "expected_task_count": len(expected_task_ids),
        "missing_expected_task_ids": missing_expected_task_ids,
        "unexpected_task_ids": unexpected_task_ids,
        "deepseek_command_count": len(deepseek_command_tasks),
        "missing_deepseek_command_tasks": missing_deepseek_command_tasks,
        "strict_passed": summary.get("strict_passed"),
        "strict_failed": summary.get("strict_failed"),
        "failure_category_counts": failure_counts,
        "merge": merge_details,
    }
    complete = (
        provider == "deepseek"
        and summary.get("task_count") == 100
        and len(results) == 100
        and len(task_ids) == 100
        and not missing_expected_task_ids
        and not unexpected_task_ids
        and len(deepseek_command_tasks) == 100
        and int(summary.get("strict_failed") or 0) == 0
    )
    if complete:
        return _requirement(
            "deepseek_live_100",
            True,
            "100 个任务均已通过真实 DeepSeek live strict gate。",
            "",
            details,
        )
    status = "provider_blocked" if _has_provider_failures(failure_counts) else "incomplete"
    strict_failed = int(summary.get("strict_failed") or 0)
    evidence = (
        f"已找到 100 任务 DeepSeek live 输出，但 strict_failed={strict_failed}，"
        f"deepseek_command_count={len(deepseek_command_tasks)}，failure_category_counts={failure_counts}。"
    )
    return {
        "id": "deepseek_live_100",
        "title": "100 个任务真实 DeepSeek live",
        "status": status,
        "status_label": _status_label(status),
        "evidence": evidence,
        "details": details,
    }


def _ablation_requirement(ablation_output_dir: Path) -> dict[str, Any]:
    summary_path = ablation_output_dir / "ablation_summary.json"
    if not summary_path.exists():
        return _requirement(
            "deepseek_ablation",
            False,
            "",
            f"找不到消融 summary：{summary_path}",
            {"summary_path": str(summary_path)},
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    variants = summary.get("variants") or []
    statuses = {str(row.get("variant") or ""): str(row.get("status") or "") for row in variants}
    failure_counts = {
        str(row.get("variant") or ""): (row.get("metrics") or {}).get("failure_category_counts") or {}
        for row in variants
    }
    expected = {"pico-full", "pico-no-memory", "pico-no-plan", "pico-no-subagent", "pico-no-skills"}
    details = {
        "summary_path": str(summary_path),
        "mode": summary.get("mode"),
        "planned_only": summary.get("planned_only"),
        "variant_count": len(variants),
        "statuses": statuses,
        "failure_counts": failure_counts,
    }
    complete = (
        summary.get("mode") == "run"
        and summary.get("planned_only") is False
        and set(statuses) == expected
        and all(status == "completed" for status in statuses.values())
    )
    if complete:
        return _requirement("deepseek_ablation", True, "五个消融变体均已完成真实 DeepSeek run。", "", details)
    provider_blocked = statuses and all(status == "provider_blocked" for status in statuses.values())
    status = "provider_blocked" if provider_blocked else "incomplete"
    return {
        "id": "deepseek_ablation",
        "title": "DeepSeek 消融矩阵",
        "status": status,
        "status_label": _status_label(status),
        "evidence": f"消融输出存在，但状态为 {statuses}。",
        "details": details,
    }


def _merge_details(live_output_dir: Path) -> dict[str, Any]:
    manifest_path = live_output_dir / "merge_manifest.json"
    if not manifest_path.exists():
        return {"present": False}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"present": True, "valid": False, "path": str(manifest_path), "error": "json_decode_error"}
    return {
        "present": True,
        "valid": True,
        "path": str(manifest_path),
        "task_count": manifest.get("task_count"),
        "replaced_task_count": manifest.get("replaced_task_count"),
        "source_count": len(manifest.get("sources") or []),
        "replaced_tasks": manifest.get("replaced_tasks") or [],
    }


def _requirement(item_id: str, passed: bool, success: str, failure: str, details: dict[str, Any]) -> dict[str, Any]:
    status = "completed" if passed else "incomplete"
    return {
        "id": item_id,
        "title": {
            "branch": "目标分支",
            "benchmark_core_100": "100 个可用 benchmark 任务",
            "deepseek_live_100": "100 个任务真实 DeepSeek live",
            "deepseek_ablation": "DeepSeek 消融矩阵",
        }.get(item_id, item_id),
        "status": status,
        "status_label": _status_label(status),
        "evidence": success if passed else failure,
        "details": details,
    }


def _result_uses_deepseek_command(result: dict[str, Any]) -> bool:
    command = ((result.get("command") or {}).get("command") or [])
    return "--provider" in command and "deepseek" in command


def _status_label(status: str) -> str:
    return {
        "completed": "已完成",
        "incomplete": "未完成",
        "provider_blocked": "Provider 不可用",
    }.get(status, status)


def _provider_blocking_reason(requirements: list[dict[str, Any]]) -> str:
    categories: set[str] = set()
    for row in requirements:
        counts = row.get("details", {}).get("failure_category_counts") or {}
        categories.update(category for category, count in counts.items() if count)
        failure_counts = row.get("details", {}).get("failure_counts") or {}
        for counts in failure_counts.values():
            if isinstance(counts, dict):
                categories.update(category for category, count in counts.items() if count)
    if "provider_insufficient_balance" in categories:
        return "DeepSeek provider 余额不足"
    if "provider_network_error" in categories:
        return "DeepSeek provider 网络错误"
    if "provider_rate_limited" in categories:
        return "DeepSeek provider 限流"
    if any(category.startswith("provider_") for category in categories):
        return "DeepSeek provider 不可用"
    return "DeepSeek provider 不可用或受限"


def _has_provider_failures(counts: dict[str, Any]) -> bool:
    return any(str(category).startswith("provider_") and count for category, count in counts.items())


def _has_non_provider_failures(requirements: list[dict[str, Any]]) -> bool:
    for row in requirements:
        counts = row.get("details", {}).get("failure_category_counts") or {}
        if any(not category.startswith("provider_") and count for category, count in counts.items()):
            return True
    return False


def _git_value(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return completed.stdout.strip()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
