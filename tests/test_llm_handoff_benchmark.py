import json
import subprocess
import sys
from pathlib import Path

from pico.evaluation.context_cost import generate_report, run_paired_experiment


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "benchmarks" / "long_session_tasks.json"


def _load_long_session_tasks():
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]


def test_long_session_tasks_define_five_fixture_backed_tasks():
    tasks = _load_long_session_tasks()

    assert len(tasks) == 5
    assert {task["category"] for task in tasks} == {"long_session"}
    assert {task["id"] for task in tasks} == {
        "multi-file-refactor",
        "debug-and-fix",
        "add-endpoint-with-test",
        "config-migration",
        "dependency-upgrade",
    }
    for task in tasks:
        assert (ROOT / task["fixture_repo"]).is_dir()
        assert 8 <= int(task["step_budget"]) <= 16
        assert len(task["scripted_outputs"]) >= 5


def test_run_paired_experiment_scripted_populates_llm_handoff_metrics(tmp_path):
    tasks = _load_long_session_tasks()[:1]

    payload = run_paired_experiment(
        tasks=tasks,
        variants=["full_orchestrator", "full_orchestrator_with_llm_handoff"],
        mode="scripted",
        provider=None,
        repetitions=1,
        output_dir=tmp_path / "work",
    )

    rows = payload["rows"]
    assert {row["variant"] for row in rows} == {
        "full_orchestrator",
        "full_orchestrator_with_llm_handoff",
    }
    assert all(row["status"] == "completed" for row in rows)
    assert all(row["verification_status"] == "passed" for row in rows)

    handoff_rows = [
        row for row in rows if row["variant"] == "full_orchestrator_with_llm_handoff"
    ]
    assert handoff_rows
    assert handoff_rows[0]["compact_summary_mode"] == "llm"
    assert isinstance(handoff_rows[0]["compact_call_input_tokens"], int)
    assert isinstance(handoff_rows[0]["compact_call_output_tokens"], int)
    assert isinstance(handoff_rows[0]["compact_net_benefit_tokens"], int)


def test_generate_report_includes_llm_handoff_comparison():
    payload = {
        "summary": {},
        "pricing": {},
        "rows": [
            {
                "task_id": "task-a",
                "variant": "full_orchestrator",
                "cost_usd": 0.01,
                "compact_net_benefit_tokens": None,
                "compact_summary_mode": "deterministic",
            },
            {
                "task_id": "task-a",
                "variant": "full_orchestrator_with_llm_handoff",
                "cost_usd": 0.012,
                "compact_net_benefit_tokens": -15,
                "compact_summary_mode": "llm",
            },
        ],
    }

    report = generate_report(payload, include_llm_handoff_comparison=True)

    assert "## LLM Handoff vs Deterministic Comparison" in report
    assert "| task-a |" in report
    assert "Median net benefit: -15 tokens" in report
    assert "Net-negative tasks: task-a" in report


def test_fixture_verifiers_pass_after_scripted_correct_state(tmp_path):
    tasks = _load_long_session_tasks()
    payload = run_paired_experiment(
        tasks=tasks,
        variants=["full_orchestrator"],
        mode="scripted",
        provider=None,
        repetitions=1,
        output_dir=tmp_path / "work",
    )

    assert len(payload["rows"]) == 5
    assert all(row["verification_status"] == "passed" for row in payload["rows"])


def test_llm_handoff_benchmark_cli_scripted_smoke(tmp_path):
    output_dir = tmp_path / "artifacts"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_llm_handoff_benchmark.py",
            "--mode",
            "scripted",
            "--output-dir",
            str(output_dir),
            "--tasks",
            str(TASKS_PATH),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert f"Results: {output_dir / 'results.json'}" in result.stdout
    assert (output_dir / "results.json").is_file()
    assert "## LLM Handoff vs Deterministic Comparison" in (
        output_dir / "report.md"
    ).read_text(encoding="utf-8")
