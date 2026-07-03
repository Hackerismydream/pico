import io
import json

from pico.kernel_acceptance import main, run_kernel_acceptance
from pico.providers.clients import FakeModelClient


def test_kernel_acceptance_no_tool_fake_flow_reports_metadata():
    report = run_kernel_acceptance(
        provider="fake",
        model="fake",
        model_client_factory=lambda scenario: FakeModelClient(
            ["<final>pico kernel no-tool acceptance ok</final>"],
            metadata=[
                {
                    "finish_reason": "stop",
                    "provider_status": "completed",
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "total_tokens": 18,
                }
            ],
        ),
        scenarios=("no-tool",),
    )

    assert report["status"] == "passed"
    assert report["run_id"].startswith("acceptance_")
    scenario = report["scenarios"][0]
    assert scenario["run_id"].startswith("invocation_")
    assert scenario["provider"] == "fake"
    assert scenario["model"] == "fake"
    assert scenario["finish_reason"] == "stop"
    assert scenario["provider_status"] == "completed"
    assert scenario["usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert scenario["tool_result_count"] == 0


def test_kernel_acceptance_readonly_fake_flow_requires_tool_and_marker():
    report = run_kernel_acceptance(
        provider="fake",
        model="fake",
        model_client_factory=lambda scenario: FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "<final>Observed pico-kernel-readonly-acceptance-marker.</final>",
            ],
            metadata=[
                {"finish_reason": "tool_use", "provider_status": "in_progress"},
                {"finish_reason": "stop", "provider_status": "completed"},
            ],
        ),
        scenarios=("read-only-tool",),
    )

    assert report["status"] == "passed"
    scenario = report["scenarios"][0]
    assert scenario["name"] == "read-only-tool"
    assert scenario["runtime_status"] == "completed"
    assert scenario["tool_result_count"] == 1
    assert scenario["finish_reason"] == "stop"
    assert "pico-kernel-readonly-acceptance-marker" in scenario["final_answer"]


def test_kernel_acceptance_writes_projection_artifacts_for_manual_live_gate(tmp_path):
    report = run_kernel_acceptance(
        provider="fake",
        model="fake",
        model_client_factory=lambda scenario: FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "<final>Observed pico-kernel-readonly-acceptance-marker.</final>",
            ],
            metadata=[
                {"finish_reason": "tool_use", "provider_status": "in_progress"},
                {"finish_reason": "stop", "provider_status": "completed"},
            ],
        ),
        scenarios=("read-only-tool",),
        artifacts_root=tmp_path / "acceptance-artifacts",
    )

    assert report["status"] == "passed"
    scenario = report["scenarios"][0]
    assert scenario["artifact_capture_error"] == ""
    assert scenario["runtime_event_schema_version"] == 2
    assert scenario["tool_evidence"][0]["name"] == "read_file"
    assert scenario["tool_evidence"][0]["status"] == "ok"
    artifacts_root = tmp_path / "acceptance-artifacts" / report["run_id"]
    for artifact in ("runtime_events", "trace", "report", "manifest"):
        path = artifacts_root / scenario["artifacts"][artifact]["path"]
        assert path.exists()
    manifest = json.loads(
        (artifacts_root / scenario["artifacts"]["manifest"]["path"]).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "completed"
    assert manifest["projections"]["export"]["final_answer"] == scenario["final_answer"]
    assert manifest["projections"]["export"]["provider_calls"][-1]["metadata"]["finish_reason"] == "stop"
    assert manifest["projections"]["export"]["tool_calls"][0]["result"]["status"] == "ok"


def test_kernel_acceptance_readonly_fake_flow_fails_without_tool():
    report = run_kernel_acceptance(
        provider="fake",
        model="fake",
        model_client_factory=lambda scenario: FakeModelClient(["<final>I skipped the tool.</final>"]),
        scenarios=("read-only-tool",),
    )

    assert report["status"] == "failed"
    scenario = report["scenarios"][0]
    assert scenario["status"] == "failed"
    assert scenario["failure_reason"] == "read-only acceptance did not complete a read-only tool call"


def test_kernel_acceptance_cli_missing_credentials_is_non_success(tmp_path, monkeypatch):
    for name in ("PICO_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = main(["--cwd", str(tmp_path), "--provider", "deepseek"], stdout=stdout, stderr=stderr)

    assert status == 2
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "skipped"
    assert payload["run_id"].startswith("acceptance_")
    assert payload["provider"] == "deepseek"
    assert "missing credentials" in payload["reason"]
    assert "missing credentials" in stderr.getvalue()
