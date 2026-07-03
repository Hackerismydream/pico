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
    "tests/test_runtime_events.py",
    "tests/test_runtime_kernel.py",
    "tests/test_projection_manager.py",
    "tests/test_projection_acceptance.py",
    "tests/test_kernel_acceptance.py",
    "tests/test_headless_task.py",
    "tests/test_run_store.py",
    "tests/test_kernel_default_gate.py",
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
REQUIRED_RUNTIME_ARTIFACTS = (
    "runtime_events",
    "trace",
    "report",
    "manifest",
)
REQUIRED_READONLY_TOOL_EVENTS = (
    "tool_call_requested",
    "tool_permission_decision",
    "tool_result",
)
REQUIRED_RUNTIME_EVENT_SCHEMA_VERSION = 2


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
        _validate_fake_provider_tests(gates["fake_provider_tests"], workspace_root, failures)
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


def _validate_fake_provider_tests(gate, workspace_root, failures):
    paths = _artifact_paths(gate, workspace_root, failures, label="fake_provider_tests")
    for path in paths:
        payload = _load_json(path, f"fake_provider_tests artifact {path}", failures)
        if not isinstance(payload, dict):
            failures.append(f"fake_provider_tests artifact must be a JSON object: {path}")
            continue
        if payload.get("artifact_type") != "kernel-fake-provider-test-run":
            failures.append(f"fake_provider_tests artifact_type must be kernel-fake-provider-test-run: {path}")
        if payload.get("status") != "passed":
            failures.append(f"fake_provider_tests artifact status must be passed: {path}")
        if payload.get("exit_code") != 0:
            failures.append(f"fake_provider_tests artifact exit_code must be 0: {path}")
        if not str(payload.get("command", "")).strip():
            failures.append(f"fake_provider_tests artifact command must be recorded: {path}")
        if not str(payload.get("commit", "")).strip():
            failures.append(f"fake_provider_tests artifact commit must be recorded: {path}")
        output = payload.get("output")
        if not isinstance(output, dict) or not any(
            str(output.get(name, "")).strip() for name in ("summary", "stdout", "stderr")
        ):
            failures.append(f"fake_provider_tests artifact output must be recorded: {path}")
        test_files = set(str(item) for item in payload.get("test_files", []) if str(item).strip())
        _validate_fake_provider_test_files(test_files, workspace_root, failures)


def _validate_fake_provider_test_files(test_files, workspace_root, failures):
    missing = [path for path in REQUIRED_FAKE_TEST_FILES if path not in test_files]
    if missing:
        failures.append("fake_provider_tests missing required test files: " + ", ".join(missing))
    for raw_path in sorted(test_files):
        path = _resolve_workspace_test_file_path(raw_path, workspace_root, failures)
        if path is not None and not path.exists():
            failures.append(f"fake_provider_tests test file must exist: {raw_path}")


def _resolve_workspace_test_file_path(raw_path, workspace_root, failures):
    path = Path(str(raw_path))
    if path.is_absolute():
        failures.append(f"fake_provider_tests test file path must be relative: {raw_path}")
        return None
    resolved = (workspace_root / path).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        failures.append(f"fake_provider_tests test file path escapes workspace: {raw_path}")
        return None
    return resolved


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
            if scenario.get("runtime_event_schema_version") != REQUIRED_RUNTIME_EVENT_SCHEMA_VERSION:
                failures.append(
                    f"live_provider_acceptance scenario {name or '<unknown>'} runtime_event_schema_version must be 2"
                )
            if not (scenario.get("finish_reason") or scenario.get("provider_status")):
                failures.append(
                    f"live_provider_acceptance scenario {name or '<unknown>'} must include provider metadata"
                )
            _validate_live_projection_artifacts(scenario, path.parent, workspace_root, failures)
    missing = [name for name in REQUIRED_LIVE_SCENARIOS if name not in seen_scenarios]
    if missing:
        failures.append("live_provider_acceptance missing scenarios: " + ", ".join(missing))


def _validate_live_projection_artifacts(scenario, base_dir, workspace_root, failures):
    name = str(scenario.get("name", "")).strip() or "<unknown>"
    artifacts = scenario.get("artifacts")
    if not isinstance(artifacts, dict):
        failures.append(f"live_provider_acceptance scenario {name} artifacts must be a JSON object")
        return

    resolved = {}
    for artifact_name in REQUIRED_RUNTIME_ARTIFACTS:
        artifact = artifacts.get(artifact_name)
        if not isinstance(artifact, dict):
            failures.append(f"live_provider_acceptance scenario {name} artifacts.{artifact_name} must be a JSON object")
            continue
        raw_path = str(artifact.get("path", "")).strip()
        if not raw_path:
            failures.append(f"live_provider_acceptance scenario {name} artifacts.{artifact_name}.path must be recorded")
            continue
        artifact_path = _resolve_referenced_artifact_path(
            raw_path,
            base_dir,
            workspace_root,
            failures,
            label=f"live_provider_acceptance scenario {name} artifacts.{artifact_name}",
        )
        if artifact_path is None:
            continue
        if not artifact_path.exists():
            failures.append(f"live_provider_acceptance scenario {name} artifacts.{artifact_name} path must exist")
            continue
        resolved[artifact_name] = artifact_path

    runtime_events = _load_runtime_event_jsonl(resolved.get("runtime_events"), failures, name)
    _validate_runtime_events_v2(runtime_events, failures, f"live_provider_acceptance scenario {name}")
    event_types = [_event_kind(event) for event in runtime_events if isinstance(event, dict)]
    missing_events = [event for event in REQUIRED_PROJECTION_EVENTS if event not in event_types]
    if missing_events:
        failures.append(
            f"live_provider_acceptance scenario {name} runtime_events missing events: "
            + ", ".join(missing_events)
        )
    if name == "read-only-tool":
        missing_tool_events = [event for event in REQUIRED_READONLY_TOOL_EVENTS if event not in event_types]
        if missing_tool_events:
            failures.append(
                f"live_provider_acceptance scenario {name} runtime_events missing tool evidence: "
                + ", ".join(missing_tool_events)
            )

    manifest = _load_json(resolved.get("manifest"), f"live_provider_acceptance scenario {name} manifest", failures)
    report = _load_json(resolved.get("report"), f"live_provider_acceptance scenario {name} report", failures)
    trace = _load_jsonl(resolved.get("trace"), failures, f"live_provider_acceptance scenario {name} trace")
    if isinstance(manifest, dict):
        if manifest.get("schema_version") != 1:
            failures.append(f"live_provider_acceptance scenario {name} manifest schema_version must be 1")
        if manifest.get("runtime_event_schema_version") != REQUIRED_RUNTIME_EVENT_SCHEMA_VERSION:
            failures.append(
                f"live_provider_acceptance scenario {name} manifest runtime_event_schema_version must be 2"
            )
        if manifest.get("status") != "completed":
            failures.append(f"live_provider_acceptance scenario {name} manifest status must be completed")
        if str(manifest.get("run_id", "")).strip() != str(scenario.get("run_id", "")).strip():
            failures.append(f"live_provider_acceptance scenario {name} manifest run_id must match scenario")
        manifest_artifacts = manifest.get("artifacts")
        if not isinstance(manifest_artifacts, dict):
            failures.append(f"live_provider_acceptance scenario {name} manifest artifacts must be a JSON object")
        else:
            for artifact_name in REQUIRED_RUNTIME_ARTIFACTS:
                artifact = manifest_artifacts.get(artifact_name)
                if not isinstance(artifact, dict) or not str(artifact.get("path", "")).strip():
                    failures.append(
                        f"live_provider_acceptance scenario {name} manifest artifacts.{artifact_name}.path must be recorded"
                    )
        export = manifest.get("projections", {}).get("export") if isinstance(manifest.get("projections"), dict) else None
        if not isinstance(export, dict):
            failures.append(f"live_provider_acceptance scenario {name} manifest export projection must be recorded")
        else:
            if export.get("final_answer") != scenario.get("final_answer"):
                failures.append(f"live_provider_acceptance scenario {name} final answer must match manifest export")
            provider_calls = export.get("provider_calls")
            if not isinstance(provider_calls, list) or not provider_calls:
                failures.append(f"live_provider_acceptance scenario {name} manifest export provider_calls must be recorded")
            elif not any(call.get("metadata") for call in provider_calls if isinstance(call, dict)):
                failures.append(f"live_provider_acceptance scenario {name} manifest export provider metadata must be recorded")
            if name == "read-only-tool":
                tool_calls = export.get("tool_calls")
                if not isinstance(tool_calls, list) or not tool_calls:
                    failures.append(f"live_provider_acceptance scenario {name} manifest export tool evidence must be recorded")
                elif not any(
                    isinstance(call, dict)
                    and call.get("read_only") is True
                    and call.get("permission", {}).get("decision") == "allow"
                    and call.get("result", {}).get("status") == "ok"
                    for call in tool_calls
                ):
                    failures.append(f"live_provider_acceptance scenario {name} manifest export tool evidence must pass")
    if isinstance(report, dict):
        if report.get("final_answer") != scenario.get("final_answer"):
            failures.append(f"live_provider_acceptance scenario {name} report final_answer must match scenario")
        provider_calls = report.get("provider_calls")
        if not isinstance(provider_calls, list) or not provider_calls:
            failures.append(f"live_provider_acceptance scenario {name} report provider_calls must be recorded")
    if not trace:
        failures.append(f"live_provider_acceptance scenario {name} trace must be non-empty")
    else:
        _validate_runtime_events_v2(trace, failures, f"live_provider_acceptance scenario {name} trace")


def _load_jsonl(path, failures, label):
    if path is None:
        return []
    try:
        return [
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception as exc:
        failures.append(f"{label} could not be read as JSONL: {exc}")
        return []


def _load_runtime_event_jsonl(path, failures, scenario_name):
    return _load_jsonl(path, failures, f"live_provider_acceptance scenario {scenario_name} runtime_events")


def _event_kind(event):
    if not isinstance(event, dict):
        return None
    return event.get("kind") or event.get("type") or event.get("event")


def _validate_runtime_events_v2(events, failures, label):
    if not events:
        failures.append(f"{label} runtime_events must be non-empty")
        return
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            failures.append(f"{label} event {index} must be a JSON object")
            continue
        if event.get("schema_version") != REQUIRED_RUNTIME_EVENT_SCHEMA_VERSION:
            failures.append(f"{label} event {index} schema_version must be 2")
        if not str(event.get("event_id", "")).strip():
            failures.append(f"{label} event {index} event_id must be recorded")
        if not str(event.get("invocation_id", "")).strip():
            failures.append(f"{label} event {index} invocation_id must be recorded")
        sequence = event.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            failures.append(f"{label} event {index} sequence must be a positive integer")
        if not str(event.get("kind", "")).strip():
            failures.append(f"{label} event {index} kind must be recorded")
        if not str(event.get("status", "")).strip():
            failures.append(f"{label} event {index} status must be recorded")
        if not str(event.get("actor", "")).strip():
            failures.append(f"{label} event {index} actor must be recorded")
        if not str(event.get("created_at", "")).strip():
            failures.append(f"{label} event {index} created_at must be recorded")
        if not isinstance(event.get("payload"), dict):
            failures.append(f"{label} event {index} payload must be a JSON object")


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
        _validate_runtime_events_v2(ledger, failures, "projection_inspection ledger")
        event_types = {_event_kind(event) for event in ledger if isinstance(event, dict)}
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
    else:
        _validate_runtime_events_v2(trace, failures, "projection_inspection trace")

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
        if runtime.get("runtime_event_schema_version") != REQUIRED_RUNTIME_EVENT_SCHEMA_VERSION:
            failures.append("headless_single_task runtime.runtime_event_schema_version must be 2")
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
            elif runtime_events_path is not None:
                runtime_events = _load_runtime_event_jsonl(runtime_events_path, failures, "headless_single_task")
                _validate_runtime_events_v2(runtime_events, failures, "headless_single_task runtime_events")

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
