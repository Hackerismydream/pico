from pico.cli import main
from pico.providers.clients import FakeModelClient
from pico.runtime_kernel import InvocationContext, RuntimeRunner, project_final_answer


def test_kernel_runner_records_no_tool_final_answer_from_events(tmp_path):
    runner = RuntimeRunner(model_client=FakeModelClient(["Kernel answer."]))

    result = runner.run(
        InvocationContext(
            user_message="Answer directly",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    event_types = [event.type for event in result.events]
    assert event_types == [
        "invocation_start",
        "user_input",
        "model_output",
        "terminal_status",
    ]
    assert result.status == "completed"
    assert result.final_answer == "Kernel answer."
    assert project_final_answer(result.events) == "Kernel answer."


def test_kernel_runner_normalizes_provider_failure(tmp_path):
    class BrokenModelClient:
        def complete(self, prompt, max_new_tokens, **kwargs):
            raise RuntimeError("backend unavailable")

    runner = RuntimeRunner(model_client=BrokenModelClient())

    result = runner.run(
        InvocationContext(
            user_message="Answer directly",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "failed"
    assert result.error_type == "provider_error"
    assert "backend unavailable" in result.error_message
    terminal = result.events[-1]
    assert terminal.type == "terminal_status"
    assert terminal.payload["status"] == "failed"
    assert terminal.payload["error_type"] == "provider_error"


def test_cli_kernel_runtime_prints_projected_final_answer(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["Projected answer."]),
    )

    status = main(["--runtime", "kernel", "--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "Projected answer."


def test_cli_kernel_runtime_can_use_fake_provider(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    monkeypatch.setenv("PICO_FAKE_MODEL_OUTPUT", "Fake provider answer.")

    status = main(["--runtime", "kernel", "--provider", "fake", "--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "Fake provider answer."


def test_cli_legacy_runtime_path_remains_explicit(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["<final>Legacy answer.</final>"]),
    )

    status = main(["--runtime", "legacy", "--cwd", str(tmp_path), "--approval", "auto", "hello"])

    assert status == 0


def test_cli_kernel_runtime_reports_provider_failure(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")

    class BrokenModelClient:
        def complete(self, prompt, max_new_tokens, **kwargs):
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr("pico.cli._build_model_client", lambda args: BrokenModelClient())

    status = main(["--runtime", "kernel", "--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert "provider_error" in captured.err
    assert "backend unavailable" in captured.err
