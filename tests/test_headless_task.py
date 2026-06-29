import json
import shlex
import sys

from pico.cli import main


def _write_spec(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _python_check(expr):
    code = f"import os, sys; sys.exit(0 if ({expr}) else 1)"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def test_headless_task_run_persists_kernel_backed_pass(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README and answer with the project fact.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is alpha.</final>",
            ],
            "verifier": _python_check("os.environ.get('PICO_FINAL_ANSWER') == 'The project fact is alpha.'"),
            "allowed_tools": ["read_file"],
            "max_steps": 4,
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "pass"
    assert payload["failure_kind"] == ""
    assert payload["task"]["id"] == "read_fact"
    assert payload["runtime"]["status"] == "completed"
    assert payload["runtime"]["run_id"]
    assert payload["runtime"]["runtime_events_relpath"].endswith("runtime_events.jsonl")
    assert payload["verifier"]["exit_code"] == 0
    assert payload["verifier"]["protected_boundary"] is True
    assert payload["boundaries"]["isolated_workspace"] != str(fixture.resolve())
    assert payload["boundaries"]["verifier_visible_to_runtime"] is False
    assert not (fixture / ".pico").exists()

    run_dir = tmp_path / "runs" / payload["task_run_id"]
    assert (run_dir / "task_run.json").exists()
    wal_path = run_dir / "task_run_wal.jsonl"
    assert wal_path.exists()
    assert (run_dir / "task_run_export.json").exists()
    wal_events = [json.loads(line) for line in wal_path.read_text(encoding="utf-8").splitlines()]
    runtime_finished = next(event for event in wal_events if event["event"] == "runtime_finished")
    assert runtime_finished["runtime_run_id"] == payload["runtime"]["run_id"]
    assert runtime_finished["runtime_events_relpath"] == payload["runtime"]["runtime_events_relpath"]
    runtime_events = run_dir / payload["runtime"]["runtime_events_relpath"]
    assert runtime_events.exists()
    event_lines = [json.loads(line) for line in runtime_events.read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in event_lines][:2] == ["invocation_start", "user_input"]
    prompt_text = next(event["payload"]["text"] for event in event_lines if event["type"] == "user_input")
    assert "PICO_FINAL_ANSWER" not in prompt_text
    assert payload["verifier"]["command"] not in prompt_text
    assert "Read README" in prompt_text


def test_headless_task_verifier_failure_is_valid_benchmark_data(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: beta\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "verifier_fail",
            "workspace": str(fixture),
            "prompt": "Read README and answer.",
            "fake_model_outputs": ["<final>Wrong answer.</final>"],
            "verifier": _python_check("False"),
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "fail"
    assert payload["failure_kind"] == "benchmark"
    assert payload["failure_category"] == "verifier_failed"
    assert payload["runtime"]["status"] == "completed"
    assert payload["verifier"]["exit_code"] == 1
    assert (tmp_path / "runs" / payload["task_run_id"] / "task_run_export.json").exists()


def test_headless_task_defaults_to_no_tools(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: locked\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "default_no_tools",
            "workspace": str(fixture),
            "prompt": "Read README and answer.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "<final>The read was denied.</final>",
            ],
            "verifier": _python_check("os.environ.get('PICO_FINAL_ANSWER') == 'The read was denied.'"),
            "max_steps": 4,
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "pass"
    assert payload["policy"]["allowed_tools"] == []

    runtime_events = tmp_path / "runs" / payload["task_run_id"] / payload["runtime"]["runtime_events_relpath"]
    events = [json.loads(line) for line in runtime_events.read_text(encoding="utf-8").splitlines()]
    permission = next(event for event in events if event["type"] == "tool_permission_decision")
    assert permission["payload"]["name"] == "read_file"
    assert permission["payload"]["decision"] == "deny"
    assert permission["payload"]["available"] is False
    assert permission["payload"]["failure_classification"] == "tool_not_allowed"


def test_headless_task_policy_denies_tools_outside_task_allowlist(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: beta\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "policy_denies_list_files",
            "workspace": str(fixture),
            "prompt": "Try to list files.",
            "fake_model_outputs": [
                '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
                "<final>The list tool was denied.</final>",
            ],
            "verifier": _python_check("os.environ.get('PICO_FINAL_ANSWER') == 'The list tool was denied.'"),
            "allowed_tools": ["read_file"],
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    runtime_events = tmp_path / "runs" / payload["task_run_id"] / payload["runtime"]["runtime_events_relpath"]
    events = [json.loads(line) for line in runtime_events.read_text(encoding="utf-8").splitlines()]
    permission = next(event for event in events if event["type"] == "tool_permission_decision")
    assert permission["payload"]["name"] == "list_files"
    assert permission["payload"]["decision"] == "deny"
    assert permission["payload"]["available"] is False
    assert permission["payload"]["failure_classification"] == "tool_not_allowed"
    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert tool_result["payload"]["status"] == "denied"


def test_headless_task_defaults_to_no_tools_when_allowlist_omitted(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: beta\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "default_deny",
            "workspace": str(fixture),
            "prompt": "Read README.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "<final>Tool was denied.</final>",
            ],
            "verifier": _python_check("os.environ.get('PICO_FINAL_ANSWER') == 'Tool was denied.'"),
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    runtime_events = tmp_path / "runs" / payload["task_run_id"] / payload["runtime"]["runtime_events_relpath"]
    events = [json.loads(line) for line in runtime_events.read_text(encoding="utf-8").splitlines()]
    permission = next(event for event in events if event["type"] == "tool_permission_decision")
    assert permission["payload"]["name"] == "read_file"
    assert permission["payload"]["available"] is False
    assert permission["payload"]["decision"] == "deny"


def test_headless_task_runtime_failure_exits_nonzero(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: gamma\n", encoding="utf-8")
    spec = _write_spec(
        tmp_path / "task.json",
        {
            "id": "runtime_fail",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": [],
            "verifier": _python_check("True"),
        },
    )

    status = main(["headless", "task", "run", str(spec), "--runs-root", str(tmp_path / "runs")])

    captured = capsys.readouterr()
    assert status == 1
    payload = json.loads(captured.out)
    assert payload["status"] == "infra_fail"
    assert payload["failure_kind"] == "infrastructure"
    assert payload["failure_category"] == "runtime_failed"
    assert payload["runtime"]["status"] == "failed"
    assert payload["verifier"]["exit_code"] is None
    assert "provider_error" in captured.err
    assert (tmp_path / "runs" / payload["task_run_id"] / "task_run_export.json").exists()
