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
from .runtime_events import RUNTIME_EVENT_SCHEMA_VERSION

HEADLESS_EXPERIMENT_SCHEMA_VERSION = 1
HEADLESS_EXPERIMENT_PROVIDER_CHOICES = ("fake", "openai", "anthropic", "deepseek", "ollama")


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
    if provider_id not in HEADLESS_EXPERIMENT_PROVIDER_CHOICES:
        choices = ", ".join(HEADLESS_EXPERIMENT_PROVIDER_CHOICES)
        raise ValueError(f"headless experiment candidate provider_id must be one of: {choices}")
    return provider_id


def _normalize_candidate_model_id(provider_id, value):
    if provider_id == "fake":
        return _normalize_fake_model_id(value)
    model_id = str(value or "").strip()
    if not model_id:
        raise ValueError(f"headless experiment candidate provider {provider_id} is missing model_id")
    return model_id


def _candidate_provider_config(raw_candidate):
    config = {}
    for source_key, target_key in (
        ("base_url", "base_url"),
        ("provider_base_url", "base_url"),
        ("host", "host"),
        ("provider_host", "host"),
    ):
        if raw_candidate.get(source_key) is not None:
            config[target_key] = str(raw_candidate[source_key]).strip()
    for source_key, target_key in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
    ):
        if raw_candidate.get(source_key) is not None:
            config[target_key] = float(raw_candidate[source_key])
    for source_key, target_key in (
        ("timeout", "timeout"),
        ("provider_timeout", "timeout"),
        ("openai_timeout", "timeout"),
        ("ollama_timeout", "timeout"),
    ):
        if raw_candidate.get(source_key) is not None:
            value = int(raw_candidate[source_key])
            if value < 1:
                raise ValueError(f"headless experiment candidate {source_key} must be positive")
            config[target_key] = value
    return config


@dataclass(frozen=True)
class HeadlessExperimentCandidate:
    id: str
    prompt: str
    prompt_sha256: str
    runtime_policy_id: str
    provider_id: str
    model_id: str
    verifier_id: str
    provider_config: dict


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
                provider_config={},
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
        provider_id = _normalize_provider_id(raw_candidate.get("provider_id", raw_candidate.get("provider", "fake")))
        candidates.append(
            HeadlessExperimentCandidate(
                id=candidate_id,
                prompt=prompt,
                prompt_sha256=prompt_sha256,
                runtime_policy_id=str(raw_candidate.get("runtime_policy_id", "kernel-readonly-v1")).strip(),
                provider_id=provider_id,
                model_id=_normalize_candidate_model_id(
                    provider_id,
                    _candidate_model_value(provider_id, raw_candidate),
                ),
                verifier_id=str(raw_candidate.get("verifier_id", _default_verifier_id(task))).strip(),
                provider_config=_candidate_provider_config(raw_candidate),
            )
        )
        seen_ids.add(candidate_id)

    for candidate in candidates:
        for field in ("runtime_policy_id", "provider_id", "model_id", "verifier_id"):
            if not getattr(candidate, field):
                raise ValueError(f"headless experiment candidate {candidate.id} is missing {field}")
    return candidates


def _candidate_model_value(provider_id, raw_candidate):
    value = raw_candidate.get("model_id", raw_candidate.get("model"))
    if value is None and provider_id == "fake":
        return "fake:default"
    return value


class HeadlessExperimentRunner:
    def __init__(self, runs_root, model_client_factory=None):
        self.runs_root = Path(runs_root).resolve()
        self.store = RunStore(self.runs_root)
        self.model_client_factory = model_client_factory

    def run(self, spec, report_path=None, resume=None):
        experiment_run_id, experiment_dir, resumed = self._resolve_experiment_run(spec, resume)
        experiment_dir.mkdir(parents=True, exist_ok=True)

        if resumed:
            self._wal(
                experiment_run_id,
                "resume_started",
                experiment_id=spec.id,
                spec_path=str(spec.spec_path),
                resume_source=str(resume),
            )
        else:
            self._wal(
                experiment_run_id,
                "experiment_started",
                experiment_id=spec.id,
                spec_path=str(spec.spec_path),
            )
        task_runner = HeadlessTaskRunner(
            experiment_dir / "task-runs",
            model_client_factory=self.model_client_factory,
        )
        task_refs = []
        reconcile_failure = None
        reusable_refs = {}
        if resumed:
            try:
                reusable_refs = self._reconcile_existing_task_runs(spec, experiment_run_id, experiment_dir)
            except ValueError as exc:
                reconcile_failure = str(exc)
                self._wal(
                    experiment_run_id,
                    "resume_rejected",
                    failure_kind="infrastructure",
                    failure_category="reconcile_failed",
                    reason=reconcile_failure,
                )

        for candidate in spec.candidates:
            candidate_task = replace(
                spec.task,
                prompt=candidate.prompt,
                provider_id=candidate.provider_id,
                model_id=candidate.model_id,
                provider_config=dict(candidate.provider_config),
            )
            identity = _build_identity(candidate, spec.task)
            identity_key = _identity_key(identity)
            if reconcile_failure is not None:
                continue
            if identity_key in reusable_refs:
                task_ref = reusable_refs[identity_key]
                task_refs.append(task_ref)
                self._wal(
                    experiment_run_id,
                    "resume_reused_task_run",
                    task_run_id=task_ref["task_run_id"],
                    status=task_ref["status"],
                    failure_kind=task_ref["failure_kind"],
                    failure_category=task_ref["failure_category"],
                    **identity,
                )
                continue
            if resumed:
                self._wal(
                    experiment_run_id,
                    "resume_rerun_required",
                    reason="no compatible completed task artifact found for identity",
                    **identity,
                )
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

        if reconcile_failure is not None:
            task_refs.append(_build_reconcile_failure_ref(spec, reconcile_failure))
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

    def _resolve_experiment_run(self, spec, resume):
        if not resume:
            experiment_run_id = _new_experiment_run_id(spec.id)
            return experiment_run_id, self.store.run_dir(experiment_run_id), False

        resume_value = Path(str(resume)).expanduser()
        if resume_value.exists() or resume_value.is_absolute() or len(resume_value.parts) > 1:
            experiment_dir = resume_value.resolve()
            if not experiment_dir.is_dir():
                raise ValueError(f"headless experiment resume directory does not exist: {experiment_dir}")
            self.runs_root = experiment_dir.parent
            self.store = RunStore(self.runs_root)
            return experiment_dir.name, experiment_dir, True

        experiment_run_id = str(resume).strip()
        if not experiment_run_id:
            raise ValueError("headless experiment resume id is empty")
        experiment_dir = self.store.run_dir(experiment_run_id)
        if not experiment_dir.is_dir():
            raise ValueError(f"headless experiment resume id does not exist: {experiment_run_id}")
        return experiment_run_id, experiment_dir, True

    def _reconcile_existing_task_runs(self, spec, experiment_run_id, experiment_dir):
        wal_events = _read_jsonl(self.store.experiment_wal_path(experiment_run_id))
        artifact_events = [event for event in wal_events if event.get("event") == "artifact_captured"]
        if not artifact_events:
            return {}

        expected_keys = {_identity_key(_build_identity(candidate, spec.task)) for candidate in spec.candidates}
        reusable_refs = {}
        for event in artifact_events:
            identity = _event_identity(event)
            identity_key = _identity_key(identity)
            if identity_key not in expected_keys:
                continue
            if identity_key in reusable_refs:
                raise ValueError(f"duplicate reusable task artifact for identity {identity_key}")
            task_ref = self._reconcile_task_artifact(experiment_dir, event, identity)
            reusable_refs[identity_key] = task_ref

        export_path = self.store.experiment_export_path(experiment_run_id)
        if reusable_refs and export_path.exists():
            export = json.loads(export_path.read_text(encoding="utf-8"))
            prior_refs = [
                row for row in export.get("task_runs", []) or []
                if _identity_key(row.get("identity", {})) in reusable_refs
            ]
            prior_summary = summarize_experiment_task_runs(prior_refs)
            if prior_summary != export.get("summary", {}):
                raise ValueError("experiment export summary disagrees with reconciled task artifacts")

        return reusable_refs

    def _reconcile_task_artifact(self, experiment_dir, event, identity):
        task_export_relpath = str(event.get("task_run_export_relpath", ""))
        if not task_export_relpath:
            raise ValueError("artifact_captured event is missing task_run_export_relpath")
        task_export_path = experiment_dir / task_export_relpath
        if not task_export_path.is_file():
            raise ValueError(f"referenced task-run export is missing: {task_export_relpath}")
        task_export = json.loads(task_export_path.read_text(encoding="utf-8"))
        task_ref = _build_task_run_ref(task_export, identity)

        artifact_paths = {
            "task_run_export_relpath": task_ref["artifacts"].get("task_run_export_relpath", ""),
            "task_run_wal_relpath": task_ref["artifacts"].get("task_run_wal_relpath", ""),
        }
        if task_ref["failure_category"] != "missing_credentials":
            artifact_paths["runtime_manifest_relpath"] = task_ref["artifacts"].get("runtime_manifest_relpath", "")
        for label, relpath in artifact_paths.items():
            if not relpath or not (experiment_dir / relpath).is_file():
                raise ValueError(f"referenced {label} is missing: {relpath}")

        task_schema_version = task_ref["runtime"].get("runtime_event_schema_version", "")
        if task_ref["failure_category"] != "missing_credentials":
            manifest = json.loads((experiment_dir / artifact_paths["runtime_manifest_relpath"]).read_text(encoding="utf-8"))
            manifest_schema_version = manifest.get("runtime_event_schema_version")
            if manifest_schema_version != task_schema_version:
                raise ValueError(
                    "runtime manifest schema version disagrees with task-run export: "
                    f"{manifest_schema_version} != {task_schema_version}"
                )
            if task_schema_version != event.get("runtime_event_schema_version"):
                raise ValueError("artifact_captured runtime schema version disagrees with task-run export")
            if task_schema_version != RUNTIME_EVENT_SCHEMA_VERSION:
                raise ValueError(
                    "reconciled task-run runtime schema version is incompatible with current runtime: "
                    f"{task_schema_version} != {RUNTIME_EVENT_SCHEMA_VERSION}"
                )

        task_identity = {
            "provider_id": str(task_export.get("policy", {}).get("model_provider", "")),
            "task_id": str(task_export.get("task", {}).get("id", "")),
            "prompt_sha256": str(task_export.get("task", {}).get("prompt_sha256", "")),
        }
        for field, actual in task_identity.items():
            if identity.get(field) != actual:
                raise ValueError(f"reconciled task-run {field} mismatch: {identity.get(field)} != {actual}")
        verifier = dict(task_export.get("verifier", {}) or {})
        if verifier.get("exit_code") is None and task_ref["failure_category"] not in {
            "missing_credentials",
            "provider_failed",
            "runtime_failed",
            "setup_failed",
            "runtime_artifact_capture_failed",
        }:
            raise ValueError("reconciled task-run is missing verifier result")

        task_ref["reused"] = True
        return task_ref

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


def _identity_key(identity):
    return tuple(
        str((identity or {}).get(field, ""))
        for field in (
            "candidate_id",
            "prompt_sha256",
            "runtime_policy_id",
            "provider_id",
            "model_id",
            "task_id",
            "verifier_id",
        )
    )


def _event_identity(event):
    return {
        "candidate_id": str(event.get("candidate_id", "")),
        "prompt_sha256": str(event.get("prompt_sha256", "")),
        "runtime_policy_id": str(event.get("runtime_policy_id", "")),
        "provider_id": str(event.get("provider_id", "")),
        "model_id": str(event.get("model_id", "")),
        "task_id": str(event.get("task_id", "")),
        "verifier_id": str(event.get("verifier_id", "")),
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


def _build_reconcile_failure_ref(spec, message):
    return {
        "task_run_id": "",
        "status": "infra_fail",
        "failure_kind": "infrastructure",
        "failure_category": "reconcile_failed",
        "infrastructure_error": message,
        "identity": {
            "task_id": spec.task.id,
        },
        "task": {
            "id": spec.task.id,
            "spec_path": str(spec.task.spec_path),
        },
        "runtime": {
            "status": "",
            "run_id": "",
            "runtime_event_schema_version": "",
            "event_count": 0,
            "event_type_counts": {},
            "usage": {},
            "cost": {},
            "terminal_error": "",
        },
        "verifier": {
            "status": "skipped",
            "exit_code": None,
            "timed_out": False,
            "protected_boundary": True,
        },
        "boundaries": {
            "verifier_visible_to_runtime": False,
        },
        "artifacts": {
            "task_run_dir_relpath": "",
            "task_run_export_relpath": "",
            "task_run_facts_relpath": "",
            "task_run_wal_relpath": "",
            "runtime_events_relpath": "",
            "trace_relpath": "",
            "runtime_report_relpath": "",
            "runtime_manifest_relpath": "",
        },
    }


def _normalize_infrastructure_failure_category(failure_category, runtime, verifier):
    if bool(verifier.get("timed_out", False)):
        return "verifier_timeout"
    if failure_category == "runtime_artifact_capture_failed":
        return failure_category
    if failure_category == "missing_credentials":
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
        "reused": sum(1 for row in task_runs if row.get("status") == "reused" or row.get("reused") is True),
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


def _read_jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    parser.add_argument(
        "--resume",
        default=None,
        help="Resume an existing experiment by run id or experiment artifact directory.",
    )
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
        result = HeadlessExperimentRunner(args.runs_root).run(
            spec,
            report_path=args.report_path,
            resume=args.resume,
        )
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
