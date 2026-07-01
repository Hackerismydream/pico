import json
import shlex
import sys

from pico.cli import main
from pico.providers.clients import FakeModelClient


RUNTIME_MANIFEST_ARTIFACTS = {
    "runtime_events": {"path": "runtime_events.jsonl"},
    "trace": {"path": "trace.jsonl"},
    "report": {"path": "report.json"},
    "manifest": {"path": "runtime_manifest.json"},
}
BASE_RUNTIME_EVENTS = {
    "invocation_start",
    "user_input",
    "model_output",
    "final_answer",
    "terminal_status",
}
READONLY_TOOL_EVENTS = {
    "tool_call_requested",
    "tool_permission_decision",
    "tool_argument_validation",
    "tool_result",
}


def _write_spec(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _python_check(expr):
    code = f"import os, sys; sys.exit(0 if ({expr}) else 1)"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _single_cli_run_dir(root):
    run_dirs = sorted((root / ".pico" / "runs").iterdir())
    assert len(run_dirs) == 1
    return run_dirs[0]


def _runtime_run_dir_from_headless_payload(task_run_dir, payload):
    manifest_path = task_run_dir / payload["runtime"]["manifest_relpath"]
    assert manifest_path.exists()
    return manifest_path.parent


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _event_kind(event):
    return event.get("kind") or event.get("type") or event.get("event")


def _assert_manifest_backed_runtime_contract(run_dir, *, final_answer, expect_readonly_tool):
    manifest = _load_json(run_dir / "runtime_manifest.json")
    report = _load_json(run_dir / "report.json")
    events = _load_jsonl(run_dir / "runtime_events.jsonl")
    trace = _load_jsonl(run_dir / "trace.jsonl")
    event_types = {_event_kind(event) for event in events}

    assert manifest["schema_version"] == 1
    assert manifest["runtime_event_schema_version"] == 2
    assert manifest["run_id"] == run_dir.name
    assert manifest["status"] == "completed"
    assert manifest["artifacts"] == RUNTIME_MANIFEST_ARTIFACTS
    assert manifest["projections"]["export"]["artifact_type"] == "kernel-runtime-export"
    assert manifest["projections"]["export"]["run_id"] == manifest["run_id"]
    assert manifest["projections"]["export"]["status"] == "completed"
    assert manifest["projections"]["export"]["final_answer"] == final_answer
    assert report["run_id"] == manifest["run_id"]
    assert report["status"] == "completed"
    assert report["final_answer"] == final_answer
    assert report["provider_calls"]
    assert trace
    assert all(event["schema_version"] == 2 for event in events)
    assert all(event["schema_version"] == 2 for event in trace)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert BASE_RUNTIME_EVENTS.issubset(event_types)
    for artifact in RUNTIME_MANIFEST_ARTIFACTS.values():
        assert (run_dir / artifact["path"]).exists()

    tool_calls = manifest["projections"]["export"]["tool_calls"]
    if expect_readonly_tool:
        assert READONLY_TOOL_EVENTS.issubset(event_types)
        assert tool_calls
        assert tool_calls[0]["name"] == "read_file"
        assert tool_calls[0]["read_only"] is True
        assert tool_calls[0]["permission"]["decision"] == "allow"
        assert tool_calls[0]["result"]["status"] == "ok"
        assert report["permission_decisions"][0]["decision"] == "allow"
        assert report["tool_calls"][0]["status"] == "ok"
    else:
        assert READONLY_TOOL_EVENTS.isdisjoint(event_types)
        assert tool_calls == []
        assert report["tool_calls"] == []

    return manifest


def test_cli_fake_provider_no_tool_acceptance_uses_manifest_contract(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("project fact: cli-no-tool\n", encoding="utf-8")
    monkeypatch.setenv("PICO_FAKE_MODEL_OUTPUT", "<final>CLI no-tool projection ok.</final>")

    status = main(
        [
            "--runtime",
            "kernel",
            "--provider",
            "fake",
            "--cwd",
            str(tmp_path),
            "answer directly",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "CLI no-tool projection ok."
    _assert_manifest_backed_runtime_contract(
        _single_cli_run_dir(tmp_path),
        final_answer="CLI no-tool projection ok.",
        expect_readonly_tool=False,
    )


def test_cli_fake_provider_readonly_tool_acceptance_uses_manifest_contract(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("project fact: cli-readonly\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>CLI read-only projection ok.</final>",
            ]
        ),
    )

    status = main(
        [
            "--runtime",
            "kernel",
            "--provider",
            "fake",
            "--approval",
            "auto",
            "--cwd",
            str(tmp_path),
            "read README",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "CLI read-only projection ok."
    _assert_manifest_backed_runtime_contract(
        _single_cli_run_dir(tmp_path),
        final_answer="CLI read-only projection ok.",
        expect_readonly_tool=True,
    )


def test_headless_fake_provider_no_tool_acceptance_uses_same_manifest_contract(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: headless-no-tool\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "headless_no_tool_projection",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": ["<final>Headless no-tool projection ok.</final>"],
            "verifier": _python_check(
                "os.environ.get('PICO_FINAL_ANSWER') == 'Headless no-tool projection ok.'"
            ),
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["status"] == "pass"
    assert payload["runtime"]["manifest_relpath"].endswith("runtime_manifest.json")
    assert payload["runtime"]["runtime_event_schema_version"] == 2
    _assert_manifest_backed_runtime_contract(
        _runtime_run_dir_from_headless_payload(tmp_path / "runs" / payload["task_run_id"], payload),
        final_answer="Headless no-tool projection ok.",
        expect_readonly_tool=False,
    )


def test_headless_fake_provider_readonly_tool_acceptance_uses_same_manifest_contract(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: headless-readonly\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "headless_readonly_projection",
            "workspace": str(fixture),
            "prompt": "Read README.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>Headless read-only projection ok.</final>",
            ],
            "verifier": _python_check(
                "os.environ.get('PICO_FINAL_ANSWER') == 'Headless read-only projection ok.'"
            ),
            "allowed_tools": ["read_file"],
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["status"] == "pass"
    assert payload["runtime"]["manifest_relpath"].endswith("runtime_manifest.json")
    assert payload["runtime"]["runtime_event_schema_version"] == 2
    _assert_manifest_backed_runtime_contract(
        _runtime_run_dir_from_headless_payload(tmp_path / "runs" / payload["task_run_id"], payload),
        final_answer="Headless read-only projection ok.",
        expect_readonly_tool=True,
    )
