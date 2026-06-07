import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from pico import cli
from pico.benchmarks import swebench
from pico.benchmarks.swebench_agent import FINAL_DIFF_COMMAND, SWEBenchAgent, initial_prompt
from pico.benchmarks.swebench_docker import CommandResult, resolve_image
from pico.testing import ScriptedModelClient


def load_script(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_file_reads_prompt_and_runs_one_shot(tmp_path, capsys):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Return final.", encoding="utf-8")
    with patch(
        "pico.cli._build_model_client",
        return_value=ScriptedModelClient(["<final>prompt file ok</final>"]),
    ):
        code = cli.main(
            [
                "--cwd",
                str(tmp_path),
                "--prompt-file",
                str(prompt),
                "--approval",
                "auto",
                "--non-interactive",
            ]
        )

    captured = capsys.readouterr()
    assert code == 0
    assert "prompt file ok" in captured.out


def test_prompt_file_with_positional_prompt_returns_2(tmp_path, capsys):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Return final.", encoding="utf-8")

    code = cli.main(["--prompt-file", str(prompt), "extra prompt"])

    captured = capsys.readouterr()
    assert code == 2
    assert "--prompt-file cannot be combined" in captured.err


def test_session_id_creates_and_reuses_fixed_session(tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Return final.", encoding="utf-8")
    clients = [
        ScriptedModelClient(["<final>first</final>"]),
        ScriptedModelClient(["<final>second</final>"]),
    ]
    argv = [
        "--cwd",
        str(tmp_path),
        "--prompt-file",
        str(prompt),
        "--session-id",
        "bench-session",
        "--approval",
        "auto",
        "--non-interactive",
    ]

    with patch("pico.cli._build_model_client", side_effect=clients):
        assert cli.main(argv) == 0
        assert cli.main(argv) == 0

    session_path = tmp_path / ".pico" / "sessions" / "bench-session.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assert session["id"] == "bench-session"
    assert [item["content"] for item in session["history"] if item["role"] == "assistant"] == [
        "first",
        "second",
    ]


def test_invalid_session_ids_and_resume_conflict_return_2(tmp_path, capsys):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Return final.", encoding="utf-8")
    for session_id in ("../x", "a/b", ".", ".."):
        code = cli.main(
            [
                "--cwd",
                str(tmp_path),
                "--prompt-file",
                str(prompt),
                "--session-id",
                session_id,
                "--approval",
                "auto",
                "--non-interactive",
            ]
        )
        assert code == 2
    code = cli.main(
        [
            "--cwd",
            str(tmp_path),
            "--prompt-file",
            str(prompt),
            "--session-id",
            "bench-session",
            "--resume",
            "latest",
            "--approval",
            "auto",
            "--non-interactive",
        ]
    )
    assert code == 2
    assert "--session-id cannot be combined" in capsys.readouterr().err


def test_non_interactive_with_approval_ask_returns_2(tmp_path, capsys):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Return final.", encoding="utf-8")

    code = cli.main(["--cwd", str(tmp_path), "--prompt-file", str(prompt), "--non-interactive"])

    captured = capsys.readouterr()
    assert code == 2
    assert "--non-interactive requires" in captured.err


def test_harness_summarizer_reads_nested_scores_and_usage(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "01-file.json").write_text(
        json.dumps(
            {
                "task_id": "01-file",
                "model_id": "pico-v3-local",
                "usage_summary": {"total_tokens": 123},
                "oracle_result": {"outcome_score": 1.0},
                "process_result": {"total": 0.8},
                "combined_result": {"combined_score": 0.8},
            }
        ),
        encoding="utf-8",
    )
    module = load_script("scripts/summarize-harness-bench.py")

    summary = module.summarize_path(results)

    assert summary["attempted_tasks"] == 1
    assert summary["oracle_passed_tasks"] == 1
    assert summary["oracle_pass_rate"] == 1.0
    assert summary["average_total_tokens"] == 123
    assert summary["average_process_score"] == 0.8
    assert summary["average_combined_score"] == 0.8


def test_swe_image_resolution_uses_official_fallback():
    assert resolve_image({"docker_image": "custom:latest"}) == "custom:latest"
    assert (
        resolve_image({"instance_id": "astropy__astropy-12907"})
        == "docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"
    )


def test_swe_initial_prompt_does_not_leak_test_or_gold_fields():
    prompt = initial_prompt(
        {
            "instance_id": "demo__demo-1",
            "problem_statement": "Fix bug.",
            "test_patch": "SECRET_TEST_PATCH",
            "patch": "SECRET_GOLD_PATCH",
            "FAIL_TO_PASS": ["SECRET_FAIL_TO_PASS"],
            "PASS_TO_PASS": ["SECRET_PASS_TO_PASS"],
            "hints_text": "SECRET_HINT",
        }
    )

    assert "Fix bug." in prompt
    assert "SECRET_TEST_PATCH" not in prompt
    assert "SECRET_GOLD_PATCH" not in prompt
    assert "SECRET_FAIL_TO_PASS" not in prompt
    assert "SECRET_PASS_TO_PASS" not in prompt
    assert "SECRET_HINT" not in prompt


def test_swe_resume_preserves_existing_prediction(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    old_patch = "diff --git a/a.py b/a.py\n"
    (output / "preds.json").write_text(
        json.dumps(
            {
                "old__case-1": {
                    "model_name_or_path": "pico-v3/model",
                    "instance_id": "old__case-1",
                    "model_patch": old_patch,
                }
            }
        ),
        encoding="utf-8",
    )
    new_patch = "diff --git a/b.py b/b.py\n"
    monkeypatch.setattr(swebench, "load_instances", lambda args: [{"instance_id": "new__case-1"}])
    monkeypatch.setattr(
        swebench,
        "run_instance",
        lambda instance, args: swebench.Trajectory(
            instance_id="new__case-1",
            model="deepseek-v4-pro",
            model_patch=new_patch,
            model_patch_chars=len(new_patch),
            exit_status="submitted",
        ),
    )

    code = swebench.main(["--output", str(output), "--provider", "deepseek"])

    preds = json.loads((output / "preds.json").read_text(encoding="utf-8"))
    assert code == 0
    assert preds["old__case-1"]["model_patch"] == old_patch
    assert preds["new__case-1"]["model_patch"] == new_patch


def test_swe_setup_error_exits_1_and_writes_summary(tmp_path, monkeypatch):
    output = tmp_path / "out"
    monkeypatch.setattr(swebench, "load_instances", lambda args: [{"instance_id": "demo__demo-1"}])
    monkeypatch.setattr("pico.benchmarks.swebench._build_model_client", lambda args: ScriptedModelClient([]))
    monkeypatch.setattr("pico.benchmarks.swebench.start_container", lambda image, timeout: (_ for _ in ()).throw(RuntimeError("docker unavailable")))

    code = swebench.main(["--output", str(output), "--provider", "deepseek"])

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    preds = json.loads((output / "preds.json").read_text(encoding="utf-8"))
    traj = json.loads((output / "demo__demo-1" / "demo__demo-1.traj.json").read_text(encoding="utf-8"))
    assert code == 1
    assert summary["setup_error_count"] == 1
    assert summary["non_empty_predictions"] == 0
    assert preds == {}
    assert "docker unavailable" in traj["setup_error"]


def test_swe_agent_collects_final_diff():
    commands = []

    def run_shell(command):
        commands.append(command)
        if command == FINAL_DIFF_COMMAND:
            return CommandResult(command, 0, "diff --git a/demo.py b/demo.py\n", "")
        return CommandResult(command, 0, "passed\n", "")

    agent = SWEBenchAgent(
        ScriptedModelClient(
            [
                '<tool name="run_shell"><command>pytest -q</command></tool>',
                "<final>done</final>",
            ]
        ),
        model="deepseek-v4-pro",
        max_steps=4,
        max_new_tokens=1024,
    )

    trajectory = agent.run({"instance_id": "demo__demo-1", "problem_statement": "Fix bug."}, run_shell)

    assert commands == ["pytest -q", FINAL_DIFF_COMMAND]
    assert trajectory.model_patch == "diff --git a/demo.py b/demo.py\n"
