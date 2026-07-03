"""Headless eval grid backed by the single-task runner."""

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from .headless import (
    HEADLESS_TASK_SCHEMA_VERSION,
    HeadlessTaskRunner,
    HeadlessTaskSpec,
    load_headless_task_spec,
    _normalize_allowed_tools,
    _normalize_fake_outputs,
)
from .run_store import RunStore

HEADLESS_EVAL_GRID_SCHEMA_VERSION = 1


def _now():
    return datetime.now(timezone.utc).isoformat()


def _slug(value):
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value).strip())
    text = "-".join(part for part in text.split("-") if part)
    return text[:48] or "grid"


def _new_grid_run_id(grid_id):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"evalgrid_{_slug(grid_id)}_{stamp}_{uuid.uuid4().hex[:6]}"


def _resolve_grid_path(raw_path, grid_spec_path):
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    return (grid_spec_path.parent / path).resolve()


def _relpath(path, root):
    return os.path.relpath(str(Path(path).resolve()), str(Path(root).resolve()))


def _join_relpath(base, child):
    if not child:
        return ""
    return str(Path(base) / child)


@dataclass(frozen=True)
class HeadlessEvalGridConfig:
    id: str
    provider: str
    model: str
    metadata: dict
    fake_model_outputs: list[str] | None
    fake_outputs_by_task: dict[str, list[str]]
    allowed_tools: list[str] | None
    max_steps: int | None
    max_new_tokens: int | None


@dataclass(frozen=True)
class HeadlessEvalGridSpec:
    id: str
    spec_path: Path
    tasks: list[HeadlessTaskSpec]
    configs: list[HeadlessEvalGridConfig]


@dataclass(frozen=True)
class HeadlessEvalGridResult:
    exit_code: int
    export: dict
    report: str


def load_headless_eval_grid_spec(path):
    spec_path = Path(path).resolve()
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("headless eval grid spec must be a JSON object")

    grid_id = str(data.get("id") or spec_path.stem).strip()
    if not grid_id:
        raise ValueError("headless eval grid spec is missing id")

    tasks = _load_grid_tasks(data.get("tasks"), spec_path)
    configs = _load_grid_configs(data.get("configs"))
    return HeadlessEvalGridSpec(id=grid_id, spec_path=spec_path, tasks=tasks, configs=configs)


def _load_grid_tasks(value, spec_path):
    if not isinstance(value, list) or not value:
        raise ValueError("headless eval grid spec must include a non-empty tasks list")
    tasks = []
    seen = set()
    for item in value:
        raw_path = item.get("path", item.get("spec", "")) if isinstance(item, dict) else item
        task = load_headless_task_spec(_resolve_grid_path(raw_path, spec_path))
        if task.id in seen:
            raise ValueError(f"headless eval grid task ids must be unique: {task.id}")
        seen.add(task.id)
        tasks.append(task)
    return tasks


def _load_grid_configs(value):
    if not isinstance(value, list) or not value:
        raise ValueError("headless eval grid spec must include a non-empty configs list")
    configs = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("headless eval grid configs must be JSON objects")
        config_id = str(item.get("id", "")).strip()
        if not config_id:
            raise ValueError("headless eval grid config is missing id")
        if config_id in seen:
            raise ValueError(f"headless eval grid config ids must be unique: {config_id}")
        seen.add(config_id)

        provider = str(item.get("provider", "fake")).strip() or "fake"
        if provider != "fake":
            raise ValueError(
                f"headless eval grid config {config_id} uses provider {provider!r}; "
                "only fake provider configs are executable in this slice"
            )

        fake_outputs = None
        if "fake_model_outputs" in item:
            fake_outputs = _normalize_fake_outputs(item["fake_model_outputs"])

        by_task = item.get("fake_outputs_by_task", {})
        if not isinstance(by_task, dict):
            raise ValueError(f"headless eval grid config {config_id} fake_outputs_by_task must be an object")
        fake_outputs_by_task = {
            str(task_id): _normalize_fake_outputs(outputs)
            for task_id, outputs in by_task.items()
        }

        allowed_tools = None
        if "allowed_tools" in item:
            allowed_tools = _normalize_allowed_tools(item.get("allowed_tools"))

        max_steps = _optional_positive_int(item, "max_steps", config_id)
        max_new_tokens = _optional_positive_int(item, "max_new_tokens", config_id)
        metadata = dict(item.get("metadata", {}) or {})
        configs.append(
            HeadlessEvalGridConfig(
                id=config_id,
                provider=provider,
                model=str(item.get("model", "")).strip(),
                metadata=metadata,
                fake_model_outputs=fake_outputs,
                fake_outputs_by_task=fake_outputs_by_task,
                allowed_tools=allowed_tools,
                max_steps=max_steps,
                max_new_tokens=max_new_tokens,
            )
        )
    return configs


def _optional_positive_int(item, key, config_id):
    if item.get(key) is None:
        return None
    value = int(item[key])
    if value < 1:
        raise ValueError(f"headless eval grid config {config_id} {key} must be positive")
    return value


class HeadlessEvalGridRunner:
    def __init__(self, runs_root):
        self.runs_root = Path(runs_root).resolve()
        self.store = RunStore(self.runs_root)

    def run(self, spec, report_path=None):
        grid_run_id = _new_grid_run_id(spec.id)
        grid_dir = self.store.run_dir(grid_run_id)
        grid_dir.mkdir(parents=True, exist_ok=True)
        task_runs_root = grid_dir / "task-runs"
        task_runner = HeadlessTaskRunner(task_runs_root)

        rows = []
        for config in spec.configs:
            for task in spec.tasks:
                configured_task = _apply_config(task, config)
                task_result = task_runner.run(configured_task)
                rows.append(_build_row(config, task, task_result.export, grid_dir))

        report_path = Path(report_path).resolve() if report_path else self.store.eval_grid_report_path(grid_run_id)
        export = _build_export(spec, grid_run_id, grid_dir, report_path, rows)
        report = render_headless_eval_grid_report(export)
        self.store.write_eval_grid_export(grid_run_id, export)
        if report_path == self.store.eval_grid_report_path(grid_run_id):
            self.store.write_eval_grid_report(grid_run_id, report)
        else:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")

        exit_code = 1 if export["summary"]["infrastructure_failed"] else 0
        return HeadlessEvalGridResult(exit_code=exit_code, export=export, report=report)


def _apply_config(task, config):
    configured = task
    if task.id in config.fake_outputs_by_task:
        configured = replace(configured, fake_model_outputs=list(config.fake_outputs_by_task[task.id]))
    elif config.fake_model_outputs is not None:
        configured = replace(configured, fake_model_outputs=list(config.fake_model_outputs))
    if config.allowed_tools is not None:
        configured = replace(configured, allowed_tools=list(config.allowed_tools))
    if config.max_steps is not None:
        configured = replace(configured, max_steps=config.max_steps)
    if config.max_new_tokens is not None:
        configured = replace(configured, max_new_tokens=config.max_new_tokens)
    return configured


def _build_row(config, task, task_export, grid_dir):
    task_run_id = str(task_export.get("task_run_id", ""))
    task_run_dir_relpath = str(Path("task-runs") / task_run_id)
    runtime = dict(task_export.get("runtime", {}) or {})
    verifier = dict(task_export.get("verifier", {}) or {})
    artifacts = dict(task_export.get("artifacts", {}) or {})
    runtime_events_relpath = _join_relpath(task_run_dir_relpath, runtime.get("runtime_events_relpath", ""))
    trace_relpath = _join_relpath(task_run_dir_relpath, runtime.get("trace_relpath", ""))
    report_relpath = _join_relpath(task_run_dir_relpath, runtime.get("report_relpath", ""))
    task_run_export_relpath = _join_relpath(task_run_dir_relpath, artifacts.get("task_run_export_relpath", ""))
    task_run_facts_relpath = _join_relpath(task_run_dir_relpath, artifacts.get("task_run_facts_relpath", ""))
    task_run_wal_relpath = _join_relpath(task_run_dir_relpath, artifacts.get("task_run_wal_relpath", ""))
    return {
        "row_id": f"{config.id}::{task.id}",
        "config": {
            "id": config.id,
            "provider": config.provider,
            "model": config.model,
            "metadata": dict(config.metadata),
            "runtime": "kernel",
        },
        "task": {
            "id": task.id,
            "spec_path": str(task.spec_path),
            "prompt_sha256": task_export.get("task", {}).get("prompt_sha256", ""),
        },
        "task_run_id": task_run_id,
        "status": str(task_export.get("status", "")),
        "failure_kind": str(task_export.get("failure_kind", "")),
        "failure_category": str(task_export.get("failure_category", "")),
        "infrastructure_error": str(task_export.get("infrastructure_error", "")),
        "runtime": {
            "status": str(runtime.get("status", "")),
            "run_id": str(runtime.get("run_id", "")),
            "event_count": int(runtime.get("event_count", 0) or 0),
            "event_type_counts": dict(runtime.get("event_type_counts", {}) or {}),
            "provider_calls": list(runtime.get("provider_calls", []) or []),
            "usage": dict(runtime.get("usage", {}) or {}),
            "cost": dict(runtime.get("cost", {}) or {}),
            "terminal_error": str(runtime.get("terminal_error", "")),
            "runtime_events_relpath": runtime_events_relpath,
        },
        "verifier": {
            "status": _verifier_status(verifier),
            "exit_code": verifier.get("exit_code"),
            "timed_out": bool(verifier.get("timed_out", False)),
            "protected_boundary": bool(verifier.get("protected_boundary", False)),
        },
        "artifacts": {
            "task_run_dir_relpath": task_run_dir_relpath,
            "task_run_export_relpath": task_run_export_relpath,
            "task_run_facts_relpath": task_run_facts_relpath,
            "task_run_wal_relpath": task_run_wal_relpath,
            "runtime_events_relpath": runtime_events_relpath,
            "trace_relpath": trace_relpath,
            "report_relpath": report_relpath,
        },
    }


def _verifier_status(verifier):
    exit_code = verifier.get("exit_code")
    if exit_code is None:
        return "skipped"
    if exit_code == 0:
        return "pass"
    return "fail"


def _build_export(spec, grid_run_id, grid_dir, report_path, rows):
    summary = summarize_grid_rows(rows)
    return {
        "artifact_type": "headless-eval-grid-export",
        "schema_version": HEADLESS_EVAL_GRID_SCHEMA_VERSION,
        "task_schema_version": HEADLESS_TASK_SCHEMA_VERSION,
        "grid_run_id": grid_run_id,
        "created_at": _now(),
        "grid": {
            "id": spec.id,
            "spec_path": str(spec.spec_path),
            "task_count": len(spec.tasks),
            "config_count": len(spec.configs),
        },
        "matrix": {
            "task_ids": [task.id for task in spec.tasks],
            "config_ids": [config.id for config in spec.configs],
            "run_count": len(rows),
        },
        "summary": summary,
        "comparison": build_grid_comparison(rows),
        "rows": rows,
        "artifacts": {
            "eval_grid_export_relpath": _relpath(Path(grid_dir) / "eval_grid_export.json", grid_dir),
            "report_relpath": _relpath(report_path, grid_dir),
        },
    }


def summarize_grid_rows(rows):
    status_counts = Counter(row.get("status", "") for row in rows if row.get("status", ""))
    failure_category_counts = Counter(
        row.get("failure_category", "")
        for row in rows
        if row.get("failure_category", "")
    )
    return {
        "total_runs": len(rows),
        "passed": sum(1 for row in rows if row.get("status") == "pass"),
        "benchmark_failed": sum(1 for row in rows if row.get("failure_kind") == "benchmark"),
        "infrastructure_failed": sum(1 for row in rows if row.get("failure_kind") == "infrastructure"),
        "status_counts": dict(sorted(status_counts.items())),
        "failure_category_counts": dict(sorted(failure_category_counts.items())),
    }


def build_grid_comparison(rows):
    by_config = {}
    by_task = {}
    for row in rows:
        by_config.setdefault(row["config"]["id"], []).append(row)
        by_task.setdefault(row["task"]["id"], []).append(row)
    return {
        "by_config": {key: summarize_grid_rows(value) for key, value in by_config.items()},
        "by_task": {key: summarize_grid_rows(value) for key, value in by_task.items()},
        "status_table": [
            {
                "config_id": row["config"]["id"],
                "task_id": row["task"]["id"],
                "status": row["status"],
                "failure_kind": row["failure_kind"],
                "failure_category": row["failure_category"],
                "runtime_status": row["runtime"]["status"],
                "verifier_status": row["verifier"]["status"],
            }
            for row in rows
        ],
    }


def render_headless_eval_grid_report(export):
    grid_id = export.get("grid", {}).get("id", "")
    summary = export.get("summary", {})
    lines = [
        f"# Headless eval grid: {grid_id}",
        "",
        f"- grid_run_id: {export.get('grid_run_id', '')}",
        f"- total_runs: {summary.get('total_runs', 0)}",
        f"- passed: {summary.get('passed', 0)}",
        f"- benchmark_failed: {summary.get('benchmark_failed', 0)}",
        f"- infrastructure_failed: {summary.get('infrastructure_failed', 0)}",
        "",
        "| config | task | status | runtime | verifier | runtime_events |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in export.get("rows", []):
        lines.append(
            "| {config} | {task} | {status} | {runtime} | {verifier} | {events} |".format(
                config=row["config"]["id"],
                task=row["task"]["id"],
                status=row["status"],
                runtime=row["runtime"]["status"],
                verifier=row["verifier"]["status"],
                events=row["artifacts"]["runtime_events_relpath"],
            )
        )
    return "\n".join(lines) + "\n"


def build_headless_eval_grid_run_parser():
    parser = argparse.ArgumentParser(
        prog="pico headless eval grid run",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Run a small fake-provider config x task matrix through the kernel-backed headless runner.",
    )
    parser.add_argument("spec", help="Path to a headless eval grid JSON spec.")
    parser.add_argument(
        "--runs-root",
        default=str(Path.cwd() / ".pico" / "headless" / "eval-grids"),
        help="Directory where eval-grid artifacts and task-run artifacts are written.",
    )
    parser.add_argument("--report-path", default=None, help="Optional Markdown report output path.")
    return parser


def run_headless_eval_grid_cli(argv):
    args = build_headless_eval_grid_run_parser().parse_args(argv)
    try:
        spec = load_headless_eval_grid_spec(args.spec)
        result = HeadlessEvalGridRunner(args.runs_root).run(spec, report_path=args.report_path)
    except Exception as exc:
        print(f"headless_eval_grid_error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.export, indent=2, sort_keys=True))
    if result.exit_code != 0:
        for row in result.export.get("rows", []):
            if row.get("failure_kind") != "infrastructure":
                continue
            message = row.get("runtime", {}).get("terminal_error") or row.get("infrastructure_error", "")
            if message:
                print(message, file=sys.stderr)
    return result.exit_code
