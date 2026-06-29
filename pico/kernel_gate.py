"""Kernel runtime default gate.

The gate intentionally validates local release-candidate artifacts instead of
running live provider calls. CI can exercise this module with fixture JSON while
manual release work decides when the manifest is written.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path


KERNEL_RELEASE_CANDIDATE_SCHEMA_VERSION = 1
DEFAULT_KERNEL_RELEASE_CANDIDATE_PATH = ".pico/kernel-release-candidate.json"
KERNEL_RELEASE_CANDIDATE_ENV = "PICO_KERNEL_RELEASE_CANDIDATE"
REQUIRED_GATES = (
    "fake_provider_tests",
    "live_provider_acceptance",
    "projection_inspection",
    "headless_single_task",
)
REQUIRED_FAKE_TEST_FILES = (
    "tests/test_runtime_kernel.py",
    "tests/test_kernel_acceptance.py",
    "tests/test_headless_task.py",
)
REQUIRED_LIVE_SCENARIOS = ("no-tool", "read-only-tool")
REQUIRED_PROJECTION_EVENTS = (
    "invocation_start",
    "user_input",
    "model_output",
    "final_answer",
    "terminal_status",
)
REQUIRED_HEADLESS_EVENTS = (
    "invocation_start",
    "user_input",
    "model_output",
    "final_answer",
    "terminal_status",
)


@dataclass(frozen=True)
class KernelGateEvaluation:
    passed: bool
    manifest_path: str
    manifest_exists: bool
    failures: tuple[str, ...]

    @property
    def reason(self):
        return "; ".join(self.failures)


def kernel_release_candidate_path(workspace_root, override=None):
    raw_path = override or os.environ.get(KERNEL_RELEASE_CANDIDATE_ENV) or DEFAULT_KERNEL_RELEASE_CANDIDATE_PATH
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path(workspace_root).resolve() / path


def evaluate_kernel_release_candidate(path=None, *, workspace_root="."):
    workspace_root = Path(workspace_root).resolve()
    manifest_path = kernel_release_candidate_path(workspace_root, path)
    failures = []
    if not manifest_path.exists():
        return KernelGateEvaluation(
            passed=False,
            manifest_path=str(manifest_path),
            manifest_exists=False,
            failures=(f"candidate manifest not found: {manifest_path}",),
        )

    manifest = _load_json(manifest_path, "candidate manifest", failures)
    if not isinstance(manifest, dict):
        failures.append("candidate manifest must be a JSON object")
        return _evaluation(manifest_path, True, failures)

    if manifest.get("schema_version") != KERNEL_RELEASE_CANDIDATE_SCHEMA_VERSION:
        failures.append(
            "candidate manifest schema_version must be "
            f"{KERNEL_RELEASE_CANDIDATE_SCHEMA_VERSION}"
        )
    if manifest.get("runtime") != "kernel":
        failures.append("candidate manifest runtime must be kernel")
    if manifest.get("status") not in {"release_candidate", "passed"}:
        failures.append("candidate manifest status must be release_candidate or passed")

    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        failures.append("candidate manifest gates must be a JSON object")
        return _evaluation(manifest_path, True, failures)
    for name in REQUIRED_GATES:
        if name not in gates:
            failures.append(f"candidate manifest is missing gate: {name}")

    if isinstance(gates.get("fake_provider_tests"), dict):
        _validate_fake_provider_tests(gates["fake_provider_tests"], failures)
    if isinstance(gates.get("live_provider_acceptance"), dict):
        _validate_live_provider_acceptance(gates["live_provider_acceptance"], workspace_root, failures)
    if isinstance(gates.get("projection_inspection"), dict):
        _validate_projection_inspection(gates["projection_inspection"], workspace_root, failures)
    if isinstance(gates.get("headless_single_task"), dict):
        _validate_headless_single_task(gates["headless_single_task"], workspace_root, failures)

    for name in REQUIRED_GATES:
        if name in gates and not isinstance(gates.get(name), dict):
            failures.append(f"gate {name} must be a JSON object")

    return _evaluation(manifest_path, True, failures)


def _evaluation(manifest_path, manifest_exists, failures):
    return KernelGateEvaluation(
        passed=not failures,
        manifest_path=str(manifest_path),
        manifest_exists=manifest_exists,
        failures=tuple(failures),
    )


def _load_json(path, label, failures):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"{label} could not be read as JSON: {exc}")
        return None


def _artifact_paths(gate, workspace_root, failures, *, label):
    raw_paths = []
    if gate.get("artifact"):
        raw_paths.append(gate["artifact"])
    raw_artifacts = gate.get("artifacts")
    if raw_artifacts is not None:
        if not isinstance(raw_artifacts, list):
            failures.append(f"gate {label} artifacts must be a list")
            return []
        raw_paths.extend(raw_artifacts)
    paths = []
    for raw_path in raw_paths:
        path = _resolve_workspace_artifact_path(raw_path, workspace_root, failures, label=label)
        if path is not None:
            paths.append(path)
    if not paths:
        failures.append(f"gate {label} must reference at least one artifact")
    return paths


def _resolve_workspace_artifact_path(raw_path, workspace_root, failures, *, label):
    path = Path(str(raw_path))
    if path.is_absolute():
        failures.append(f"gate {label} artifact path must be relative: {raw_path}")
        return None
    resolved = (workspace_root / path).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        failures.append(f"gate {label} artifact path escapes workspace: {raw_path}")
        return None
    return resolved


def _resolve_referenced_artifact_path(raw_path, base_dir, workspace_root, failures, *, label):
    path = Path(str(raw_path))
    if path.is_absolute():
        resolved = path.resolve()
        boundary = workspace_root
    else:
        resolved = (base_dir / path).resolve()
        boundary = base_dir.resolve()
    try:
        resolved.relative_to(boundary)
    except ValueError:
        failures.append(f"{label} path escapes artifact boundary: {raw_path}")
        return None
    return resolved


def _validate_fake_provider_tests(gate, failures):
    if gate.get("status") != "passed":
        failures.append("fake_provider_tests status must be passed")
    if not str(gate.get("command", "")).strip():
        failures.append("fake_provider_tests command must be recorded")
    test_files = set(str(item) for item in gate.get("test_files", []) if str(item).strip())
    missing = [path for path in REQUIRED_FAKE_TEST_FILES if path not in test_files]
    if missing:
        failures.append("fake_provider_tests missing required test files: " + ", ".join(missing))


def _validate_live_provider_acceptance(gate, workspace_root, failures):
    paths = _artifact_paths(gate, workspace_root, failures, label="live_provider_acceptance")
    seen_scenarios = set()
    for path in paths:
        payload = _load_json(path, f"live_provider_acceptance artifact {path}", failures)
        if not isinstance(payload, dict):
            failures.append(f"live_provider_acceptance artifact must be a JSON object: {path}")
            continue
        if payload.get("status") != "passed":
            failures.append(f"live_provider_acceptance artifact status must be passed: {path}")
        provider = str(payload.get("provider", "")).strip()
        if not provider or provider == "fake":
            failures.append(f"live_provider_acceptance artifact must record a real provider: {path}")
        scenarios = payload.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            failures.append(f"live_provider_acceptance artifact must include scenarios: {path}")
            continue
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                failures.append(f"live_provider_acceptance scenario must be an object: {path}")
                continue
            name = str(scenario.get("name", "")).strip()
            if name:
                seen_scenarios.add(name)
            if scenario.get("status") != "passed":
                failures.append(f"live_provider_acceptance scenario {name or '<unknown>'} must pass")
            if scenario.get("runtime_status") != "completed":
                failures.append(
                    f"live_provider_acceptance scenario {name or '<unknown>'} runtime_status must be completed"
                )
            if not (scenario.get("finish_reason") or scenario.get("provider_status")):
                failures.append(
                    f"live_provider_acceptance scenario {name or '<unknown>'} must include provider metadata"
                )
    missing = [name for name in REQUIRED_LIVE_SCENARIOS if name not in seen_scenarios]
    if missing:
        failures.append("live_provider_acceptance missing scenarios: " + ", ".join(missing))


def _validate_projection_inspection(gate, workspace_root, failures):
    paths = _artifact_paths(gate, workspace_root, failures, label="projection_inspection")
    if not paths:
        return
    path = paths[0]
    payload = _load_json(path, f"projection_inspection artifact {path}", failures)
    if not isinstance(payload, dict):
        failures.append(f"projection_inspection artifact must be a JSON object: {path}")
        return

    ledger = payload.get("ledger")
    if not isinstance(ledger, list) or not ledger:
        failures.append("projection_inspection ledger must be a non-empty list")
    else:
        event_types = {event.get("type") for event in ledger if isinstance(event, dict)}
        missing_events = [event for event in REQUIRED_PROJECTION_EVENTS if event not in event_types]
        if missing_events:
            failures.append("projection_inspection ledger missing events: " + ", ".join(missing_events))

    run_ids = []
    for view in ("session", "report", "export"):
        view_payload = payload.get(view)
        if not isinstance(view_payload, dict):
            failures.append(f"projection_inspection {view} view must be a JSON object")
            continue
        if view_payload.get("status") != "completed":
            failures.append(f"projection_inspection {view} status must be completed")
        run_id = str(view_payload.get("run_id", "")).strip()
        if not run_id:
            failures.append(f"projection_inspection {view} must include run_id")
        else:
            run_ids.append(run_id)
    if len(set(run_ids)) > 1:
        failures.append("projection_inspection session/report/export run_id values must match")

    trace = payload.get("trace")
    if not isinstance(trace, list) or not trace:
        failures.append("projection_inspection trace must be a non-empty list")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        failures.append("projection_inspection artifacts view must be a JSON object")
    else:
        for name in ("runtime_events", "trace", "report"):
            artifact = artifacts.get(name)
            if not isinstance(artifact, dict):
                failures.append(f"projection_inspection artifacts.{name} must be a JSON object")
                continue
            raw_path = str(artifact.get("path", "")).strip()
            if not raw_path:
                failures.append(f"projection_inspection artifacts.{name}.path must be recorded")
                continue
            artifact_path = _resolve_referenced_artifact_path(
                raw_path,
                path.parent,
                workspace_root,
                failures,
                label=f"projection_inspection artifacts.{name}",
            )
            if artifact_path is not None and not artifact_path.exists():
                failures.append(f"projection_inspection artifacts.{name} path must exist")


def _validate_headless_single_task(gate, workspace_root, failures):
    paths = _artifact_paths(gate, workspace_root, failures, label="headless_single_task")
    if not paths:
        return
    path = paths[0]
    payload = _load_json(path, f"headless_single_task artifact {path}", failures)
    if not isinstance(payload, dict):
        failures.append(f"headless_single_task artifact must be a JSON object: {path}")
        return
    if payload.get("artifact_type") != "headless-task-run-export":
        failures.append("headless_single_task artifact_type must be headless-task-run-export")
    if payload.get("status") != "pass":
        failures.append("headless_single_task status must be pass")
    if payload.get("failure_kind"):
        failures.append("headless_single_task failure_kind must be empty")

    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        failures.append("headless_single_task runtime must be a JSON object")
    else:
        if runtime.get("status") != "completed":
            failures.append("headless_single_task runtime.status must be completed")
        if not str(runtime.get("run_id", "")).strip():
            failures.append("headless_single_task runtime.run_id must be recorded")
        event_counts = runtime.get("event_type_counts")
        if not isinstance(event_counts, dict):
            failures.append("headless_single_task runtime.event_type_counts must be recorded")
        else:
            missing_events = [event for event in REQUIRED_HEADLESS_EVENTS if int(event_counts.get(event, 0) or 0) < 1]
            if missing_events:
                failures.append("headless_single_task runtime missing events: " + ", ".join(missing_events))
        relpath = str(runtime.get("runtime_events_relpath", "")).strip()
        if not relpath:
            failures.append("headless_single_task runtime_events_relpath must be recorded")
        else:
            runtime_events_path = _resolve_referenced_artifact_path(
                relpath,
                path.parent,
                workspace_root,
                failures,
                label="headless_single_task runtime_events_relpath",
            )
            if runtime_events_path is not None and not runtime_events_path.exists():
                failures.append("headless_single_task runtime_events_relpath must exist")

    verifier = payload.get("verifier")
    if not isinstance(verifier, dict):
        failures.append("headless_single_task verifier must be a JSON object")
    else:
        if verifier.get("exit_code") != 0:
            failures.append("headless_single_task verifier.exit_code must be 0")
        if verifier.get("protected_boundary") is not True:
            failures.append("headless_single_task verifier.protected_boundary must be true")
        if verifier.get("timed_out") is True:
            failures.append("headless_single_task verifier must not time out")

    boundaries = payload.get("boundaries")
    if not isinstance(boundaries, dict):
        failures.append("headless_single_task boundaries must be a JSON object")
    elif boundaries.get("verifier_visible_to_runtime") is not False:
        failures.append("headless_single_task verifier_visible_to_runtime must be false")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        failures.append("headless_single_task policy must be a JSON object")
    else:
        if policy.get("runtime") != "kernel":
            failures.append("headless_single_task policy.runtime must be kernel")
        if policy.get("model_provider") != "fake":
            failures.append("headless_single_task policy.model_provider must be fake")
        if policy.get("fail_closed") is not True:
            failures.append("headless_single_task policy.fail_closed must be true")
