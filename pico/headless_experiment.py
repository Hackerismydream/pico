"""Headless experiment controller over kernel-backed task runs."""

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from .headless import HEADLESS_TASK_SCHEMA_VERSION, HeadlessTaskRunner, HeadlessTaskSpec, load_headless_task_spec
from .run_store import RunStore

HEADLESS_EXPERIMENT_SCHEMA_VERSION = 1


def _now():
    return datetime.now(timezone.utc).isoformat()


def _slug(value):
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value).strip())
    text = "-".join(part for part in text.split("-") if part)
    return text[:48] or "experiment"


def _new_experiment_run_id(experiment_id):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"experiment_{_slug(experiment_id)}_{stamp}_{uuid.uuid4().hex[:6]}"


def _resolve_spec_path(raw_path, spec_path):
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    return (spec_path.parent / path).resolve()


def _relpath(path, root):
    return os.path.relpath(str(Path(path).resolve()), str(Path(root).resolve()))


def _join_relpath(base, child):
    if not child:
        return ""
    return str(Path(base) / child)


def _sha256_text(text):
    return "sha256:" + hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _default_verifier_id(task):
    return "verifier:" + hashlib.sha256(task.verifier_command.encode("utf-8")).hexdigest()[:16]


def _normalize_fake_model_id(value):
    model_id = str(value or "fake:default").strip()
    if not model_id:
        raise ValueError("fake-provider headless experiment candidate is missing model_id")
    if not model_id.startswith("fake:"):
        raise ValueError("fake-provider headless experiment candidate model_id must start with fake:")
    return model_id


def _normalize_provider_id(value):
    provider_id = str(value or "fake").strip()
    if provider_id != "fake":
        raise ValueError("headless experiment candidates currently support provider_id=fake only")
    return provider_id


@dataclass(frozen=True)
class HeadlessExperimentCandidate:
    id: str
    prompt: str
    prompt_sha256: str
    runtime_policy_id: str
    provider_id: str
    model_id: str
    verifier_id: str


@dataclass(frozen=True)
class HeadlessExperimentSpec:
    id: str
    spec_path: Path
    task: HeadlessTaskSpec
    candidates: list[HeadlessExperimentCandidate]


@dataclass(frozen=True)
class HeadlessExperimentResult:
    exit_code: int
    export: dict
    report: str


def load_headless_experiment_spec(path):
    spec_path = Path(path).resolve()
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("headless experiment spec must be a JSON object")

    experiment_id = str(data.get("id") or spec_path.stem).strip()
    if not experiment_id:
        raise ValueError("headless experiment spec is missing id")

    task_value = data.get("task", data.get("task_spec"))
    if isinstance(task_value, dict):
        task_value = task_value.get("path", task_value.get("spec"))
    if not str(task_value or "").strip():
        raise ValueError(f"headless experiment {experiment_id} is missing task")
    task = load_headless_task_spec(_resolve_spec_path(task_value, spec_path))
    candidates = _load_candidates(data, task)
    return HeadlessExperimentSpec(id=experiment_id, spec_path=spec_path, task=task, candidates=candidates)


def _load_candidates(data, task):
    raw_candidates = data.get("candidates")
    if raw_candidates is None:
        return [
            HeadlessExperimentCandidate(
                id="default",
                prompt=task.prompt,
                prompt_sha256=_sha256_text(task.prompt),
                runtime_policy_id="kernel-readonly-v1",
                provider_id="fake",
                model_id="fake:default",
                verifier_id=_default_verifier_id(task),
            )
        ]
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("headless experiment candidates must be a non-empty list")

    candidates = []
    seen_ids = set()
    for index, raw_candidate in enumerate(raw_candidates):
        if not isinstance(raw_candidate, dict):
            raise ValueError(f"headless experiment candidate #{index + 1} must be a JSON object")
        candidate_id = str(raw_candidate.get("id", "")).strip()
        if not candidate_id:
            raise ValueError(f"headless experiment candidate #{index + 1} is missing id")
        if candidate_id in seen_ids:
            raise ValueError(f"duplicate headless experiment candidate id: {candidate_id}")
        prompt = str(raw_candidate.get("prompt", raw_candidate.get("prompt_body", ""))).strip()
        if not prompt:
            raise ValueError(f"headless experiment candidate {candidate_id} is missing prompt")
        computed_prompt_sha256 = _sha256_text(prompt)
        prompt_sha256 = str(raw_candidate.get("prompt_sha256", computed_prompt_sha256)).strip()
        if prompt_sha256 != computed_prompt_sha256:
            raise ValueError(f"headless experiment candidate {candidate_id} prompt_sha256 does not match prompt")
        candidates.append(
            HeadlessExperimentCandidate(
                id=candidate_id,
                prompt=prompt,
                prompt_sha256=prompt_sha256,
                runtime_policy_id=str(raw_candidate.get("runtime_policy_id", "kernel-readonly-v1")).strip(),
                provider_id=_normalize_provider_id(raw_candidate.get("provider_id", "fake")),
                model_id=_normalize_fake_model_id(raw_candidate.get("model_id", "fake:default")),
                verifier_id=str(raw_candidate.get("verifier_id", _default_verifier_id(task))).strip(),
            )
        )
        seen_ids.add(candidate_id)

    for candidate in candidates:
        for field in ("runtime_policy_id", "provider_id", "model_id", "verifier_id"):
            if not getattr(candidate, field):
                raise ValueError(f"headless experiment candidate {candidate.id} is missing {field}")
    return candidates


class HeadlessExperimentRunner:
    def __init__(self, runs_root):
        self.runs_root = Path(runs_root).resolve()
        self.store = RunStore(self.runs_root)

    def run(self, spec, report_path=None):
        experiment_run_id = _new_experiment_run_id(spec.id)
        experiment_dir = self.store.run_dir(experiment_run_id)
        experiment_dir.mkdir(parents=True, exist_ok=True)

        self._wal(
            experiment_run_id,
            "experiment_started",
            experiment_id=spec.id,
            spec_path=str(spec.spec_path),
        )
        task_runner = HeadlessTaskRunner(experiment_dir / "task-runs")
        task_refs = []
        for candidate in spec.candidates:
            candidate_task = replace(spec.task, prompt=candidate.prompt)
            identity = _build_identity(candidate, spec.task)
            self._wal(
                experiment_run_id,
                "task_scheduled",
                task_spec_path=str(spec.task.spec_path),
                **identity,
            )
            self._wal(experiment_run_id, "task_started", **identity)

            task_result = task_runner.run(candidate_task)
            task_export = task_result.export
            task_ref = _build_task_run_ref(task_export, identity)
            task_refs.append(task_ref)

            self._wal(
                experiment_run_id,
                "task_finished",
                task_run_id=task_ref["task_run_id"],
                status=task_ref["status"],
                failure_kind=task_ref["failure_kind"],
                failure_category=task_ref["failure_category"],
                **identity,
            )
            self._wal(
                experiment_run_id,
                "artifact_captured",
                task_run_id=task_ref["task_run_id"],
                task_run_export_relpath=task_ref["artifacts"]["task_run_export_relpath"],
                runtime_manifest_relpath=task_ref["artifacts"]["runtime_manifest_relpath"],
                runtime_event_schema_version=task_ref["runtime"]["runtime_event_schema_version"],
                **identity,
            )

        summary = summarize_experiment_task_runs(task_refs)
        report_path = Path(report_path).resolve() if report_path else self.store.experiment_report_path(experiment_run_id)
        export = _build_export(spec, experiment_run_id, experiment_dir, report_path, task_refs, summary)
        report = render_headless_experiment_report(export)
        self.store.write_experiment_export(experiment_run_id, export)
        if report_path == self.store.experiment_report_path(experiment_run_id):
            self.store.write_experiment_report(experiment_run_id, report)
        else:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
        self._wal(experiment_run_id, "experiment_finished", summary=summary)

        exit_code = 1 if summary["infrastructure_failed"] else 0
        return HeadlessExperimentResult(exit_code=exit_code, export=export, report=report)

    def _wal(self, experiment_run_id, event, **payload):
        self.store.append_experiment_wal(
            experiment_run_id,
            {
                "event": event,
                "created_at": _now(),
                "experiment_run_id": experiment_run_id,
                **payload,
            },
        )


def _build_identity(candidate, task):
    return {
        "candidate_id": candidate.id,
        "prompt_sha256": candidate.prompt_sha256,
        "runtime_policy_id": candidate.runtime_policy_id,
        "provider_id": candidate.provider_id,
        "model_id": candidate.model_id,
        "task_id": task.id,
        "verifier_id": candidate.verifier_id,
    }


def _candidate_ref(candidate):
    return {
        "id": candidate.id,
        "prompt_sha256": candidate.prompt_sha256,
        "runtime_policy_id": candidate.runtime_policy_id,
        "provider_id": candidate.provider_id,
        "model_id": candidate.model_id,
        "verifier_id": candidate.verifier_id,
    }


def _build_task_run_ref(task_export, identity):
    task_run_id = str(task_export.get("task_run_id", ""))
    task_run_dir_relpath = str(Path("task-runs") / task_run_id)
    runtime = dict(task_export.get("runtime", {}) or {})
    policy = dict(task_export.get("policy", {}) or {})
    artifacts = dict(task_export.get("artifacts", {}) or {})
    verifier = dict(task_export.get("verifier", {}) or {})
    boundaries = dict(task_export.get("boundaries", {}) or {})
    actual_provider_id = str(policy.get("model_provider", ""))
    if actual_provider_id and identity.get("provider_id") != actual_provider_id:
        raise ValueError(
            "headless experiment candidate provider_id does not match task-run provider: "
            f"{identity.get('provider_id')} != {actual_provider_id}"
        )
    classification = _classify_task_export(task_export, runtime, verifier)
    return {
        "task_run_id": task_run_id,
        "status": classification["status"],
        "failure_kind": classification["failure_kind"],
        "failure_category": classification["failure_category"],
        "infrastructure_error": str(task_export.get("infrastructure_error", "")),
        "identity": dict(identity),
        "task": dict(task_export.get("task", {}) or {}),
        "runtime": {
            "status": str(runtime.get("status", "")),
            "run_id": str(runtime.get("run_id", "")),
            "runtime_event_schema_version": runtime.get("runtime_event_schema_version", ""),
            "event_count": int(runtime.get("event_count", 0) or 0),
            "event_type_counts": dict(runtime.get("event_type_counts", {}) or {}),
            "usage": dict(runtime.get("usage", {}) or {}),
            "cost": dict(runtime.get("cost", {}) or {}),
            "terminal_error": str(runtime.get("terminal_error", "")),
        },
        "verifier": {
            "status": _verifier_status(verifier),
            "exit_code": verifier.get("exit_code"),
            "timed_out": bool(verifier.get("timed_out", False)),
            "protected_boundary": bool(verifier.get("protected_boundary", False)),
        },
        "boundaries": {
            "verifier_visible_to_runtime": bool(boundaries.get("verifier_visible_to_runtime", False)),
        },
        "artifacts": {
            "task_run_dir_relpath": task_run_dir_relpath,
            "task_run_export_relpath": _join_relpath(task_run_dir_relpath, artifacts.get("task_run_export_relpath", "")),
            "task_run_facts_relpath": _join_relpath(task_run_dir_relpath, artifacts.get("task_run_facts_relpath", "")),
            "task_run_wal_relpath": _join_relpath(task_run_dir_relpath, artifacts.get("task_run_wal_relpath", "")),
            "runtime_events_relpath": _join_relpath(task_run_dir_relpath, runtime.get("runtime_events_relpath", "")),
            "trace_relpath": _join_relpath(task_run_dir_relpath, runtime.get("trace_relpath", "")),
            "runtime_report_relpath": _join_relpath(task_run_dir_relpath, runtime.get("report_relpath", "")),
            "runtime_manifest_relpath": _join_relpath(task_run_dir_relpath, runtime.get("manifest_relpath", "")),
        },
    }


def _classify_task_export(task_export, runtime, verifier):
    status = str(task_export.get("status", ""))
    failure_kind = str(task_export.get("failure_kind", ""))
    failure_category = str(task_export.get("failure_category", ""))
    verifier_status = _verifier_status(verifier)

    if status == "pass":
        if verifier_status == "pass":
            return {"status": "pass", "failure_kind": "", "failure_category": ""}
        return {
            "status": "infra_fail",
            "failure_kind": "infrastructure",
            "failure_category": "verifier_boundary_invalid",
        }

    if failure_kind == "benchmark":
        if verifier_status == "fail":
            return {
                "status": "fail",
                "failure_kind": "benchmark",
                "failure_category": failure_category or "verifier_failed",
            }
        return {
            "status": "infra_fail",
            "failure_kind": "infrastructure",
            "failure_category": "verifier_boundary_invalid",
        }

    if failure_kind == "infrastructure":
        return {
            "status": status or "infra_fail",
            "failure_kind": "infrastructure",
            "failure_category": _normalize_infrastructure_failure_category(failure_category, runtime, verifier),
        }

    if status in {"skipped", "reused"}:
        return {"status": status, "failure_kind": failure_kind, "failure_category": failure_category}

    return {"status": status, "failure_kind": failure_kind, "failure_category": failure_category}


def _normalize_infrastructure_failure_category(failure_category, runtime, verifier):
    if bool(verifier.get("timed_out", False)):
        return "verifier_timeout"
    if failure_category == "runtime_artifact_capture_failed":
        return failure_category
    if failure_category == "setup_failed":
        return failure_category
    if failure_category == "runtime_failed":
        if str(runtime.get("error_type", "")) == "provider_error":
            return "provider_failed"
        return "runtime_failed"
    return failure_category or "infrastructure_failed"


def _verifier_status(verifier):
    exit_code = verifier.get("exit_code")
    if exit_code is None:
        return "skipped"
    if exit_code == 0:
        return "pass"
    return "fail"


def summarize_experiment_task_runs(task_runs):
    status_counts = Counter(row.get("status", "") for row in task_runs if row.get("status", ""))
    failure_kind_counts = Counter(
        row.get("failure_kind", "")
        for row in task_runs
        if row.get("failure_kind", "")
    )
    failure_category_counts = Counter(
        row.get("failure_category", "")
        for row in task_runs
        if row.get("failure_category", "")
    )
    benchmark_failed = sum(1 for row in task_runs if row.get("failure_kind") == "benchmark")
    passed = sum(1 for row in task_runs if row.get("status") == "pass")
    scored_runs = passed + benchmark_failed
    return {
        "total_runs": len(task_runs),
        "passed": passed,
        "benchmark_failed": benchmark_failed,
        "infrastructure_failed": sum(1 for row in task_runs if row.get("failure_kind") == "infrastructure"),
        "skipped": sum(1 for row in task_runs if row.get("status") == "skipped"),
        "reused": sum(1 for row in task_runs if row.get("status") == "reused"),
        "scored_runs": scored_runs,
        "benchmark_pass_rate": (passed / scored_runs) if scored_runs else None,
        "status_counts": dict(sorted(status_counts.items())),
        "failure_kind_counts": dict(sorted(failure_kind_counts.items())),
        "failure_category_counts": dict(sorted(failure_category_counts.items())),
    }


def _build_export(spec, experiment_run_id, experiment_dir, report_path, task_refs, summary):
    first_task_ref = task_refs[0] if task_refs else {}
    return {
        "artifact_type": "headless-experiment-export",
        "schema_version": HEADLESS_EXPERIMENT_SCHEMA_VERSION,
        "task_schema_version": HEADLESS_TASK_SCHEMA_VERSION,
        "experiment_run_id": experiment_run_id,
        "created_at": _now(),
        "experiment": {
            "id": spec.id,
            "spec_path": str(spec.spec_path),
        },
        "candidates": [_candidate_ref(candidate) for candidate in spec.candidates],
        "summary": summary,
        "runtime_event_schema_version": first_task_ref.get("runtime", {}).get("runtime_event_schema_version", ""),
        "task_run": first_task_ref,
        "task_runs": task_refs,
        "artifacts": {
            "experiment_wal_relpath": _relpath(Path(experiment_dir) / "experiment_wal.jsonl", experiment_dir),
            "experiment_export_relpath": _relpath(Path(experiment_dir) / "experiment_export.json", experiment_dir),
            "report_relpath": _relpath(report_path, experiment_dir),
        },
    }


def render_headless_experiment_report(export):
    experiment_id = export.get("experiment", {}).get("id", "")
    summary = export.get("summary", {})
    task_runs = list(export.get("task_runs", []) or [])
    if not task_runs and export.get("task_run"):
        task_runs = [export.get("task_run", {})]
    lines = [
        f"# Headless experiment: {experiment_id}",
        "",
        f"- experiment_run_id: {export.get('experiment_run_id', '')}",
        f"- total_runs: {summary.get('total_runs', 0)}",
        f"- passed: {summary.get('passed', 0)}",
        f"- benchmark_failed: {summary.get('benchmark_failed', 0)}",
        f"- infrastructure_failed: {summary.get('infrastructure_failed', 0)}",
        f"- skipped: {summary.get('skipped', 0)}",
        f"- reused: {summary.get('reused', 0)}",
        f"- scored_runs: {summary.get('scored_runs', 0)}",
        f"- benchmark_pass_rate: {summary.get('benchmark_pass_rate', '')}",
        f"- runtime_event_schema_version: {export.get('runtime_event_schema_version', '')}",
        "",
        "| candidate | prompt_sha256 | runtime_policy | provider | model | task | verifier_id | task_run | status | failure_kind | failure_category | runtime | verifier | task_export | runtime_manifest |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for task_run in task_runs:
        identity = task_run.get("identity", {})
        artifacts = task_run.get("artifacts", {})
        lines.append("| {candidate} | {prompt} | {policy} | {provider} | {model} | {task} | {verifier_id} | {task_run} | {status} | {failure_kind} | {failure_category} | {runtime} | {verifier} | {task_export} | {manifest} |".format(
            candidate=identity.get("candidate_id", ""),
            prompt=identity.get("prompt_sha256", ""),
            policy=identity.get("runtime_policy_id", ""),
            provider=identity.get("provider_id", ""),
            model=identity.get("model_id", ""),
            task=task_run.get("task", {}).get("id", ""),
            verifier_id=identity.get("verifier_id", ""),
            task_run=task_run.get("task_run_id", ""),
            status=task_run.get("status", ""),
            failure_kind=task_run.get("failure_kind", ""),
            failure_category=task_run.get("failure_category", ""),
            runtime=task_run.get("runtime", {}).get("status", ""),
            verifier=task_run.get("verifier", {}).get("status", ""),
            task_export=artifacts.get("task_run_export_relpath", ""),
            manifest=artifacts.get("runtime_manifest_relpath", ""),
        ))
    return "\n".join(lines) + "\n"


def build_headless_experiment_run_parser():
    parser = argparse.ArgumentParser(
        prog="pico headless experiment run",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Run one fake-provider headless task and wrap it in experiment-level evidence.",
    )
    parser.add_argument("spec", help="Path to a headless experiment JSON spec.")
    parser.add_argument(
        "--runs-root",
        default=str(Path.cwd() / ".pico" / "headless" / "experiments"),
        help="Directory where experiment artifacts and task-run artifacts are written.",
    )
    parser.add_argument("--report-path", default=None, help="Optional Markdown report output path.")
    parser.add_argument(
        "--fake-output",
        dest="fake_outputs",
        action="append",
        default=None,
        help="Override task fake_model_outputs. Repeat for multi-step fake provider runs.",
    )
    parser.add_argument("--max-steps", type=int, default=None, help="Override the task runtime step budget.")
    parser.add_argument("--max-new-tokens", type=int, default=None, help="Override the task model output token budget.")
    return parser


def run_headless_experiment_cli(argv):
    args = build_headless_experiment_run_parser().parse_args(argv)
    try:
        spec = load_headless_experiment_spec(args.spec)
        task = spec.task
        if args.fake_outputs is not None:
            task = replace(task, fake_model_outputs=list(args.fake_outputs))
        if args.max_steps is not None:
            task = replace(task, max_steps=int(args.max_steps))
        if args.max_new_tokens is not None:
            task = replace(task, max_new_tokens=int(args.max_new_tokens))
        if task is not spec.task:
            spec = replace(spec, task=task)
        result = HeadlessExperimentRunner(args.runs_root).run(spec, report_path=args.report_path)
    except Exception as exc:
        print(f"headless_experiment_error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.export, indent=2, sort_keys=True))
    if result.exit_code != 0:
        task_run = result.export.get("task_run", {})
        message = (
            task_run.get("runtime", {}).get("terminal_error")
            or task_run.get("infrastructure_error", "")
        )
        if message:
            print(message, file=sys.stderr)
    return result.exit_code
