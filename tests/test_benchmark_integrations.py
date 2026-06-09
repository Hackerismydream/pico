import importlib.util
import json
from pathlib import Path

from pico.benchmarks import swebench
from pico.benchmarks.swebench_agent import (
    FINAL_DIFF_COMMAND,
    SUBMISSION_COMMAND,
    SUBMISSION_SENTINEL,
    SWEBenchAgent,
    _format_command_result,
    extract_submission,
    initial_prompt,
    inspect_model_patch,
)
from pico.benchmarks.swebench_docker import CommandResult, resolve_image
from pico.providers.errors import ProviderError
from pico.testing import ScriptedModelClient


def load_script(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    assert "make the smallest plausible source patch" in prompt
    assert SUBMISSION_COMMAND in prompt
    assert "A natural-language final answer is ignored" in prompt


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


def test_swe_resume_can_skip_existing_empty_prediction(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    (output / "preds.json").write_text(
        json.dumps(
            {
                "empty__case-1": {
                    "model_name_or_path": "pico-v3/model",
                    "instance_id": "empty__case-1",
                    "model_patch": "",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(swebench, "load_instances", lambda args: [{"instance_id": "empty__case-1"}])
    monkeypatch.setattr(
        swebench,
        "run_instance",
        lambda instance, args: swebench.Trajectory(
            instance_id="empty__case-1",
            model="deepseek-v4-pro",
            model_patch="diff --git a/new.py b/new.py\n",
            model_patch_chars=28,
            exit_status="submitted",
        ),
    )

    default_code = swebench.main(["--output", str(output), "--provider", "deepseek"])
    default_preds = json.loads((output / "preds.json").read_text(encoding="utf-8"))
    assert default_code == 0
    assert default_preds["empty__case-1"]["model_patch"]

    default_preds["empty__case-1"]["model_patch"] = ""
    (output / "preds.json").write_text(json.dumps(default_preds), encoding="utf-8")
    skip_code = swebench.main(
        [
            "--output",
            str(output),
            "--provider",
            "deepseek",
            "--skip-existing-empty-predictions",
        ]
    )
    skipped_preds = json.loads((output / "preds.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))

    assert skip_code == 0
    assert skipped_preds["empty__case-1"]["model_patch"] == ""
    assert summary["attempted_instances"] == 0
    assert summary["skipped_instances"] == 1


def test_swe_summary_ignores_predictions_outside_selected_scope(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    old_patch = "diff --git a/old.py b/old.py\n"
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
    monkeypatch.setattr(swebench, "load_instances", lambda args: [{"instance_id": "new__case-1"}])
    monkeypatch.setattr(
        swebench,
        "run_instance",
        lambda instance, args: swebench.Trajectory(
            instance_id="new__case-1",
            model="deepseek-v4-pro",
            setup_error="docker unavailable",
            exit_status="setup_error",
        ),
    )

    code = swebench.main(["--output", str(output), "--provider", "deepseek"])

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert code == 1
    assert summary["selected_instances"] == 1
    assert summary["non_empty_predictions"] == 0
    assert summary["total_predictions_in_file"] == 1
    assert summary["failed_instance_ids"] == ["new__case-1"]
    assert summary["exit_status_counts"] == {"setup_error": 1}


def test_swe_redo_existing_clears_stale_patch_before_failed_rerun(tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    stale_patch = "diff --git a/stale.py b/stale.py\n"
    (output / "preds.json").write_text(
        json.dumps(
            {
                "demo__case-1": {
                    "model_name_or_path": "pico-v3/model",
                    "instance_id": "demo__case-1",
                    "model_patch": stale_patch,
                },
                "other__case-1": {
                    "model_name_or_path": "pico-v3/model",
                    "instance_id": "other__case-1",
                    "model_patch": "diff --git a/other.py b/other.py\n",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(swebench, "load_instances", lambda args: [{"instance_id": "demo__case-1"}])
    monkeypatch.setattr(
        swebench,
        "run_instance",
        lambda instance, args: swebench.Trajectory(
            instance_id="demo__case-1",
            model="deepseek-v4-pro",
            setup_error="docker unavailable",
            exit_status="setup_error",
        ),
    )

    code = swebench.main(["--output", str(output), "--provider", "deepseek", "--redo-existing"])

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    preds = json.loads((output / "preds.json").read_text(encoding="utf-8"))
    assert code == 1
    assert "demo__case-1" not in preds
    assert "other__case-1" in preds
    assert summary["non_empty_predictions"] == 0
    assert summary["total_predictions_in_file"] == 1
    assert summary["empty_patch_count"] == 1


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


def test_swe_provider_build_error_writes_model_error_summary(tmp_path, monkeypatch):
    output = tmp_path / "out"
    monkeypatch.setattr(swebench, "load_instances", lambda args: [{"instance_id": "demo__demo-1"}])
    monkeypatch.setattr(
        "pico.benchmarks.swebench._build_model_client",
        lambda args: (_ for _ in ()).throw(RuntimeError("bad config")),
    )

    code = swebench.main(["--output", str(output), "--provider", "deepseek"])

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    preds = json.loads((output / "preds.json").read_text(encoding="utf-8"))
    traj = json.loads((output / "demo__demo-1" / "demo__demo-1.traj.json").read_text(encoding="utf-8"))
    assert code == 1
    assert summary["model_error_count"] == 1
    assert summary["non_empty_predictions"] == 0
    assert preds == {}
    assert "bad config" in traj["model_error"]


def test_swe_summarizer_preserves_zero_resolved(tmp_path):
    output = tmp_path / "out"
    eval_report = tmp_path / "eval"
    output.mkdir()
    eval_report.mkdir()
    (output / "summary.json").write_text(
        json.dumps({"selected_instances": 1, "attempted_instances": 1, "non_empty_predictions": 1}),
        encoding="utf-8",
    )
    (output / "preds.json").write_text(json.dumps({"demo__demo-1": {"model_patch": "diff"}}), encoding="utf-8")
    (eval_report / "report.json").write_text(json.dumps({"resolved": 0, "total": 1}), encoding="utf-8")
    module = load_script("scripts/summarize-swebench.py")

    summary = module.summarize(output, eval_report)

    assert summary["resolved_instances"] == 0
    assert summary["resolved_rate"] == 0.0


def test_swe_summarizer_counts_empty_predictions_from_preds(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "summary.json").write_text(
        json.dumps({"selected_instances": 2, "attempted_instances": 1, "empty_patch_count": 1}),
        encoding="utf-8",
    )
    (output / "preds.json").write_text(
        json.dumps(
            {
                "demo__demo-1": {"model_patch": "diff"},
                "demo__demo-2": {"model_patch": ""},
                "demo__demo-3": {"model_patch": ""},
            }
        ),
        encoding="utf-8",
    )
    module = load_script("scripts/summarize-swebench.py")

    summary = module.summarize(output)

    assert summary["predictions_count"] == 3
    assert summary["empty_patch_count"] == 2


def test_swe_summarizer_includes_contract_and_patch_warning_counts(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "summary.json").write_text(
        json.dumps(
            {
                "selected_instances": 1,
                "attempted_instances": 1,
                "experiment_label": "slice20-b",
                "submission_contract": "sentinel",
                "non_empty_predictions": 0,
                "exit_status_counts": {"rejected_patch": 1},
                "patch_warning_counts": {"test_file_in_patch": 1},
                "patch_pollution_count": 1,
            }
        ),
        encoding="utf-8",
    )
    (output / "preds.json").write_text(json.dumps({"demo__demo-1": {"model_patch": ""}}), encoding="utf-8")
    module = load_script("scripts/summarize-swebench.py")

    summary = module.summarize(output)

    assert summary["experiment_label"] == "slice20-b"
    assert summary["submission_contract"] == "sentinel"
    assert summary["exit_status_counts"] == {"rejected_patch": 1}
    assert summary["patch_warning_counts"] == {"test_file_in_patch": 1}
    assert summary["patch_pollution_count"] == 1


def test_swe_summarizer_uses_submitted_instances_for_eval_rate(tmp_path):
    output = tmp_path / "out"
    eval_report = tmp_path / "eval"
    output.mkdir()
    eval_report.mkdir()
    (output / "summary.json").write_text(
        json.dumps({"selected_instances": 1, "attempted_instances": 1, "non_empty_predictions": 1}),
        encoding="utf-8",
    )
    (output / "preds.json").write_text(json.dumps({"demo__demo-1": {"model_patch": "diff"}}), encoding="utf-8")
    (eval_report / "report.json").write_text(
        json.dumps(
            {
                "total_instances": 300,
                "submitted_instances": 1,
                "completed_instances": 1,
                "resolved_instances": 1,
                "empty_patch_instances": 299,
            }
        ),
        encoding="utf-8",
    )
    module = load_script("scripts/summarize-swebench.py")

    summary = module.summarize(output, eval_report)

    assert summary["submitted_instances"] == 1
    assert summary["completed_instances"] == 1
    assert summary["empty_patch_count"] == 299
    assert summary["resolved_instances"] == 1
    assert summary["resolved_rate"] == 1.0


def test_swe_ab_slice_selector_builds_stratified_filter(tmp_path):
    report = tmp_path / "official.json"
    report.write_text(
        json.dumps(
            {
                "empty_patch_ids": [f"empty__case-{index}" for index in range(12, 0, -1)],
                "resolved_ids": [f"resolved__case-{index}" for index in range(8, 0, -1)],
                "unresolved_ids": [f"unresolved__case-{index}" for index in range(7, 0, -1)],
            }
        ),
        encoding="utf-8",
    )
    module = load_script("scripts/select-swebench-ab-slice.py")

    selection = module.select_slice(report, empty_count=2, resolved_count=1, unresolved_count=1)

    assert selection["counts"] == {
        "empty_patch": 2,
        "resolved": 1,
        "unresolved": 1,
        "total": 4,
    }
    assert selection["groups"]["empty_patch"] == ["empty__case-1", "empty__case-10"]
    assert selection["groups"]["resolved"] == ["resolved__case-1"]
    assert selection["groups"]["unresolved"] == ["unresolved__case-1"]
    assert selection["filter_regex"].startswith("^(?:")


def test_swe_summarizer_prefers_official_report_when_directory_has_summaries(tmp_path):
    output = tmp_path / "out"
    eval_report = tmp_path / "eval"
    output.mkdir()
    eval_report.mkdir()
    (output / "summary.json").write_text(
        json.dumps({"selected_instances": 1, "attempted_instances": 1, "non_empty_predictions": 1}),
        encoding="utf-8",
    )
    (output / "preds.json").write_text(json.dumps({"demo__demo-1": {"model_patch": "diff"}}), encoding="utf-8")
    (eval_report / "a-summary.json").write_text(
        json.dumps({"resolved_instances": 1, "resolved_rate": None}),
        encoding="utf-8",
    )
    (eval_report / "z-official-report.json").write_text(
        json.dumps({"total_instances": 300, "submitted_instances": 1, "resolved_instances": 1}),
        encoding="utf-8",
    )
    module = load_script("scripts/summarize-swebench.py")

    summary = module.summarize(output, eval_report)

    assert summary["submitted_instances"] == 1
    assert summary["resolved_rate"] == 1.0


def test_swe_agent_collects_final_diff_in_legacy_contract():
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
        submission_contract="legacy-final-diff",
    )

    trajectory = agent.run({"instance_id": "demo__demo-1", "problem_statement": "Fix bug."}, run_shell)

    assert commands == ["pytest -q", FINAL_DIFF_COMMAND]
    assert trajectory.model_patch == "diff --git a/demo.py b/demo.py\n"


def test_swe_agent_submits_patch_only_via_sentinel():
    commands = []
    patch = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n"

    def run_shell(command):
        commands.append(command)
        if command == SUBMISSION_COMMAND:
            return CommandResult(command, 0, f"{SUBMISSION_SENTINEL}\n{patch}", "")
        return CommandResult(command, 0, "passed\n", "")

    agent = SWEBenchAgent(
        ScriptedModelClient(
            [
                '<tool name="run_shell"><command>pytest -q</command></tool>',
                f'<tool name="run_shell"><command>{SUBMISSION_COMMAND}</command></tool>',
            ]
        ),
        model="deepseek-v4-pro",
        max_steps=4,
        max_new_tokens=1024,
    )

    trajectory = agent.run({"instance_id": "demo__demo-1", "problem_statement": "Fix bug."}, run_shell)

    assert commands == ["pytest -q", SUBMISSION_COMMAND]
    assert trajectory.exit_status == "submitted"
    assert trajectory.model_patch == patch


def test_swe_agent_rejects_natural_language_final_without_sentinel():
    commands = []

    def run_shell(command):
        commands.append(command)
        if command == FINAL_DIFF_COMMAND:
            return CommandResult(command, 0, "diff --git a/demo.py b/demo.py\n", "")
        return CommandResult(command, 0, "passed\n", "")

    agent = SWEBenchAgent(
        ScriptedModelClient(["<final>done</final>"]),
        model="deepseek-v4-pro",
        max_steps=1,
        max_new_tokens=1024,
    )

    trajectory = agent.run({"instance_id": "demo__demo-1", "problem_statement": "Fix bug."}, run_shell)

    assert commands == [FINAL_DIFF_COMMAND]
    assert trajectory.model_patch == ""
    assert trajectory.exit_status == "missing_submission_sentinel"
    assert "requires submitting a patch" in trajectory.steps[0]["parse_error"]


def test_swe_agent_rejects_polluted_submitted_patch():
    patch = "diff --git a/tests/test_demo.py b/tests/test_demo.py\n--- a/tests/test_demo.py\n+++ b/tests/test_demo.py\n"

    def run_shell(command):
        return CommandResult(command, 0, f"{SUBMISSION_SENTINEL}\n{patch}", "")

    agent = SWEBenchAgent(
        ScriptedModelClient([f'<tool name="run_shell"><command>{SUBMISSION_COMMAND}</command></tool>']),
        model="deepseek-v4-pro",
        max_steps=2,
        max_new_tokens=1024,
    )

    trajectory = agent.run({"instance_id": "demo__demo-1", "problem_statement": "Fix bug."}, run_shell)

    assert trajectory.model_patch == ""
    assert trajectory.rejected_model_patch_chars == len(patch)
    assert trajectory.exit_status == "rejected_patch"
    assert "test_file_in_patch" in trajectory.patch_warnings


def test_swe_submission_extraction_requires_first_stdout_line_and_zero_exit():
    assert (
        extract_submission(CommandResult(SUBMISSION_COMMAND, 0, f"{SUBMISSION_SENTINEL}\npatch", ""))
        == "patch"
    )
    assert extract_submission(CommandResult(SUBMISSION_COMMAND, 1, f"{SUBMISSION_SENTINEL}\npatch", "")) is None
    assert extract_submission(CommandResult(SUBMISSION_COMMAND, 0, f"noise\n{SUBMISSION_SENTINEL}\npatch", "")) is None


def test_swe_patch_inspection_flags_tests_and_patch_txt():
    patch = "\n".join(
        [
            "diff --git a/pkg/source.py b/pkg/source.py",
            "diff --git a/tests/test_source.py b/tests/test_source.py",
            "diff --git a/patch.txt b/patch.txt",
        ]
    )

    warnings = inspect_model_patch(patch)

    assert "test_file_in_patch" in warnings
    assert "patch_txt_in_patch" in warnings


def test_swe_agent_emits_progress_after_each_step():
    snapshots = []

    def run_shell(command):
        if command == SUBMISSION_COMMAND:
            return CommandResult(
                command,
                0,
                f"{SUBMISSION_SENTINEL}\ndiff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n",
                "",
            )
        return CommandResult(command, 0, "passed\n", "")

    agent = SWEBenchAgent(
        ScriptedModelClient(
                [
                    '<tool name="run_shell"><command>pytest -q</command></tool>',
                    f'<tool name="run_shell"><command>{SUBMISSION_COMMAND}</command></tool>',
                ]
            ),
        model="deepseek-v4-pro",
        max_steps=4,
        max_new_tokens=1024,
    )

    agent.run(
        {"instance_id": "demo__demo-1", "problem_statement": "Fix bug."},
        run_shell,
        on_step=lambda trajectory: snapshots.append(len(trajectory.steps)),
    )

    assert snapshots == [1, 2]


def test_swe_agent_blocks_broad_cat_source_commands():
    commands = []

    def run_shell(command):
        commands.append(command)
        if command == FINAL_DIFF_COMMAND:
            return CommandResult(command, 0, "diff --git a/demo.py b/demo.py\n", "")
        return CommandResult(command, 0, "unexpected\n", "")

    agent = SWEBenchAgent(
        ScriptedModelClient(
            [
                '<tool name="run_shell"><command>cat /testbed/pkg/module.py</command></tool>',
                "<final>done</final>",
            ]
        ),
        model="deepseek-v4-pro",
        max_steps=4,
        max_new_tokens=1024,
    )

    trajectory = agent.run({"instance_id": "demo__demo-1", "problem_statement": "Fix bug."}, run_shell)

    assert commands == [FINAL_DIFF_COMMAND]
    assert trajectory.steps[0]["tool_result"]["returncode"] == 2
    assert "Broad cat commands are disabled" in trajectory.steps[0]["tool_result"]["stderr"]


def test_swe_agent_retries_retryable_provider_errors():
    class FlakyClient:
        model = "deepseek-v4-pro"

        def __init__(self):
            self.calls = 0

        def complete_result(self, prompt, max_new_tokens, **kwargs):
            del prompt, max_new_tokens, kwargs
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("empty", provider="anthropic", code="empty_response", retryable=True)
            return ScriptedModelClient(
                [f'<tool name="run_shell"><command>{SUBMISSION_COMMAND}</command></tool>']
            ).complete_result("", 1)

    commands = []

    def run_shell(command):
        commands.append(command)
        return CommandResult(
            command,
            0,
            f"{SUBMISSION_SENTINEL}\ndiff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n",
            "",
        )

    client = FlakyClient()
    agent = SWEBenchAgent(client, model="deepseek-v4-pro", max_steps=2, max_new_tokens=1024)

    trajectory = agent.run({"instance_id": "demo__demo-1", "problem_statement": "Fix bug."}, run_shell)

    assert client.calls == 2
    assert trajectory.model_patch.startswith("diff --git a/demo.py b/demo.py")


def test_swe_tool_feedback_nudges_after_too_much_inspection():
    text = _format_command_result(
        CommandResult("grep -n target file.py", 0, "match\n", ""),
        remaining_steps=5,
        read_only_steps=6,
    )

    assert "Remaining tool calls before step limit: 5" in text
    assert "next useful step should modify source code" in text
