import json
import shlex
import sys

from pico.cli import main


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _python_check(expr):
    code = f"import os, sys; sys.exit(0 if ({expr}) else 1)"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _task_spec(tmp_path, task_id, answer):
    fixture = tmp_path / f"fixture-{task_id}"
    fixture.mkdir()
    (fixture / "README.md").write_text(f"project fact: {answer}\n", encoding="utf-8")
    return _write_json(
        tmp_path / f"{task_id}.json",
        {
            "id": task_id,
            "workspace": str(fixture),
            "prompt": "Answer with the project fact.",
            "fake_model_outputs": [f"<final>{answer}</final>"],
            "verifier": _python_check(f"os.environ.get('PICO_FINAL_ANSWER') == {answer!r}"),
        },
    )


def test_headless_eval_grid_runs_config_task_matrix_and_writes_projection(tmp_path, capsys):
    alpha = _task_spec(tmp_path, "alpha", "alpha answer")
    beta = _task_spec(tmp_path, "beta", "beta answer")
    grid = _write_json(
        tmp_path / "grid.json",
        {
            "id": "tiny-grid",
            "tasks": [str(alpha), str(beta)],
            "configs": [
                {"id": "fake-default", "provider": "fake", "model": "scripted-default"},
                {"id": "fake-repeat", "provider": "fake", "model": "scripted-repeat"},
            ],
        },
    )

    status = main(["headless", "eval", "grid", "run", str(grid), "--runs-root", str(tmp_path / "grids")])

    captured = capsys.readouterr()
    assert status == 0
    payload = json.loads(captured.out)
    assert payload["artifact_type"] == "headless-eval-grid-export"
    assert payload["grid"]["id"] == "tiny-grid"
    assert payload["summary"] == {
        "total_runs": 4,
        "passed": 4,
        "benchmark_failed": 0,
        "infrastructure_failed": 0,
        "status_counts": {"pass": 4},
        "failure_category_counts": {},
    }
    assert payload["comparison"]["by_config"]["fake-default"]["passed"] == 2
    assert payload["comparison"]["by_task"]["alpha"]["passed"] == 2
    assert len(payload["comparison"]["status_table"]) == 4

    grid_dir = tmp_path / "grids" / payload["grid_run_id"]
    assert json.loads((grid_dir / "eval_grid_export.json").read_text(encoding="utf-8")) == payload
    assert (grid_dir / payload["artifacts"]["report_relpath"]).exists()
    for row in payload["rows"]:
        assert row["status"] == "pass"
        assert row["runtime"]["status"] == "completed"
        assert row["runtime"]["run_id"]
        assert row["runtime"]["usage"] == {}
        assert row["runtime"]["cost"] == {}
        assert row["verifier"]["status"] == "pass"
        assert row["verifier"]["exit_code"] == 0
        assert row["artifacts"]["task_run_export_relpath"].endswith("task_run_export.json")
        assert (grid_dir / row["artifacts"]["task_run_export_relpath"]).exists()
        assert (grid_dir / row["artifacts"]["runtime_events_relpath"]).exists()


def test_headless_eval_grid_keeps_benchmark_failure_as_zero_exit(tmp_path, capsys):
    alpha = _task_spec(tmp_path, "alpha", "alpha answer")
    grid = _write_json(
        tmp_path / "grid.json",
        {
            "id": "benchmark-grid",
            "tasks": [str(alpha)],
            "configs": [
                {"id": "fake-good", "provider": "fake"},
                {
                    "id": "fake-wrong-answer",
                    "provider": "fake",
                    "fake_outputs_by_task": {"alpha": ["<final>wrong answer</final>"]},
                },
            ],
        },
    )

    status = main(["headless", "eval", "grid", "run", str(grid), "--runs-root", str(tmp_path / "grids")])

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["summary"]["passed"] == 1
    assert payload["summary"]["benchmark_failed"] == 1
    assert payload["summary"]["infrastructure_failed"] == 0
    assert payload["comparison"]["by_config"]["fake-wrong-answer"]["benchmark_failed"] == 1
    failed = next(row for row in payload["rows"] if row["config"]["id"] == "fake-wrong-answer")
    assert failed["status"] == "fail"
    assert failed["failure_kind"] == "benchmark"
    assert failed["failure_category"] == "verifier_failed"
    assert failed["runtime"]["status"] == "completed"
    assert failed["verifier"]["status"] == "fail"


def test_headless_eval_grid_infrastructure_failure_exits_nonzero_and_keeps_rows(tmp_path, capsys):
    alpha = _task_spec(tmp_path, "alpha", "alpha answer")
    grid = _write_json(
        tmp_path / "grid.json",
        {
            "id": "infra-grid",
            "tasks": [str(alpha)],
            "configs": [
                {"id": "fake-good", "provider": "fake"},
                {
                    "id": "fake-empty",
                    "provider": "fake",
                    "fake_outputs_by_task": {"alpha": []},
                },
            ],
        },
    )

    status = main(["headless", "eval", "grid", "run", str(grid), "--runs-root", str(tmp_path / "grids")])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert status == 1
    assert payload["summary"]["total_runs"] == 2
    assert payload["summary"]["passed"] == 1
    assert payload["summary"]["infrastructure_failed"] == 1
    infra = next(row for row in payload["rows"] if row["config"]["id"] == "fake-empty")
    assert infra["status"] == "infra_fail"
    assert infra["failure_kind"] == "infrastructure"
    assert infra["failure_category"] == "runtime_failed"
    assert infra["runtime"]["status"] == "failed"
    assert infra["verifier"]["status"] == "skipped"
    assert "provider_error" in captured.err


def test_headless_eval_grid_report_summarizes_rows(tmp_path, capsys):
    alpha = _task_spec(tmp_path, "alpha", "alpha answer")
    report_path = tmp_path / "grid-report.md"
    grid = _write_json(
        tmp_path / "grid.json",
        {
            "id": "report-grid",
            "tasks": [str(alpha)],
            "configs": [{"id": "fake-default", "provider": "fake"}],
        },
    )

    status = main(
        [
            "headless",
            "eval",
            "grid",
            "run",
            str(grid),
            "--runs-root",
            str(tmp_path / "grids"),
            "--report-path",
            str(report_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["artifacts"]["report_relpath"] == "../../grid-report.md"
    report = report_path.read_text(encoding="utf-8")
    assert "# Headless eval grid: report-grid" in report
    assert "| fake-default | alpha | pass | completed | pass |" in report
