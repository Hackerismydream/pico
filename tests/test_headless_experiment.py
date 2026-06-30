import json
import hashlib
import shlex
import sys

from pico.cli import main
from pico.headless_experiment import HeadlessExperimentRunner, load_headless_experiment_spec


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _python_check(expr):
    code = f"import os, sys; sys.exit(0 if ({expr}) else 1)"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _sha256(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_headless_experiment_wraps_one_task_with_wal_and_artifact_refs(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: experiment-alpha\n", encoding="utf-8")
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README and answer with the project fact.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is experiment-alpha.</final>",
            ],
            "verifier": _python_check(
                "os.environ.get('PICO_FINAL_ANSWER') == 'The project fact is experiment-alpha.'"
            ),
            "allowed_tools": ["read_file"],
            "max_steps": 4,
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-smoke",
            "task": str(task_spec),
        },
    )

    status = main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(tmp_path / "experiments"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    payload = json.loads(captured.out)
    assert payload["artifact_type"] == "headless-experiment-export"
    assert payload["experiment"]["id"] == "runtime-lab-smoke"
    assert payload["summary"] == {
        "total_runs": 1,
        "passed": 1,
        "benchmark_failed": 0,
        "infrastructure_failed": 0,
        "status_counts": {"pass": 1},
        "failure_category_counts": {},
    }
    assert payload["runtime_event_schema_version"] == 2

    experiment_dir = tmp_path / "experiments" / payload["experiment_run_id"]
    assert json.loads((experiment_dir / "experiment_export.json").read_text(encoding="utf-8")) == payload
    assert (experiment_dir / payload["artifacts"]["report_relpath"]).exists()
    assert (experiment_dir / payload["artifacts"]["experiment_wal_relpath"]).exists()

    task = payload["task_run"]
    assert task["task"]["id"] == "read_fact"
    assert task["task_run_id"]
    assert task["status"] == "pass"
    assert task["identity"]["provider_id"] == "fake"
    assert task["identity"]["model_id"] == "fake:default"
    assert task["runtime"]["status"] == "completed"
    assert task["runtime"]["runtime_event_schema_version"] == 2
    assert task["artifacts"]["task_run_export_relpath"].endswith("task_run_export.json")
    assert task["artifacts"]["runtime_manifest_relpath"].endswith("runtime_manifest.json")
    assert (experiment_dir / task["artifacts"]["task_run_export_relpath"]).exists()
    assert (experiment_dir / task["artifacts"]["task_run_wal_relpath"]).exists()
    assert (experiment_dir / task["artifacts"]["runtime_manifest_relpath"]).exists()

    wal_events = [
        json.loads(line)
        for line in (experiment_dir / payload["artifacts"]["experiment_wal_relpath"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["event"] for event in wal_events] == [
        "experiment_started",
        "task_scheduled",
        "task_started",
        "task_finished",
        "artifact_captured",
        "experiment_finished",
    ]
    assert all(event["experiment_run_id"] == payload["experiment_run_id"] for event in wal_events)
    assert wal_events[2]["task_id"] == "read_fact"
    assert wal_events[3]["task_run_id"] == task["task_run_id"]
    assert wal_events[4]["task_run_export_relpath"] == task["artifacts"]["task_run_export_relpath"]
    assert wal_events[4]["runtime_manifest_relpath"] == task["artifacts"]["runtime_manifest_relpath"]

    report = (experiment_dir / payload["artifacts"]["report_relpath"]).read_text(encoding="utf-8")
    assert "# Headless experiment: runtime-lab-smoke" in report
    assert "passed: 1" in report
    assert task["artifacts"]["task_run_export_relpath"] in report


def test_headless_experiment_records_candidate_runtime_and_verifier_identity(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: identity-alpha\n", encoding="utf-8")
    prompt = "Read README and answer with the project fact."
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "This task prompt should be replaced by the candidate prompt.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is identity-alpha.</final>",
            ],
            "verifier": _python_check(
                "os.environ.get('PICO_FINAL_ANSWER') == 'The project fact is identity-alpha.'"
            ),
            "allowed_tools": ["read_file"],
            "max_steps": 4,
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-identity",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": prompt,
                    "prompt_sha256": _sha256(prompt),
                    "runtime_policy_id": "kernel-readonly-v1",
                    "provider_id": "fake",
                    "model_id": "fake:identity-model",
                    "verifier_id": "readme-verifier-v1",
                }
            ],
        },
    )

    status = main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(tmp_path / "experiments"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    payload = json.loads(captured.out)
    identity = payload["task_run"]["identity"]
    assert identity == {
        "candidate_id": "candidate-a",
        "prompt_sha256": _sha256(prompt),
        "runtime_policy_id": "kernel-readonly-v1",
        "provider_id": "fake",
        "model_id": "fake:identity-model",
        "task_id": "read_fact",
        "verifier_id": "readme-verifier-v1",
    }
    assert payload["candidates"] == [
        {
            "id": "candidate-a",
            "prompt_sha256": _sha256(prompt),
            "runtime_policy_id": "kernel-readonly-v1",
            "provider_id": "fake",
            "model_id": "fake:identity-model",
            "verifier_id": "readme-verifier-v1",
        }
    ]

    experiment_dir = tmp_path / "experiments" / payload["experiment_run_id"]
    report = (experiment_dir / payload["artifacts"]["report_relpath"]).read_text(encoding="utf-8")
    assert "candidate-a" in report
    assert "fake:identity-model" in report
    assert "readme-verifier-v1" in report


def test_headless_experiment_rejects_non_fake_candidate_provider_before_running(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README.",
            "fake_model_outputs": ["<final>unused</final>"],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-nonfake-provider",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": "Read README.",
                    "prompt_sha256": _sha256("Read README."),
                    "provider_id": "deepseek",
                    "model_id": "deepseek-chat",
                }
            ],
        },
    )

    status = main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(tmp_path / "experiments"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "provider_id=fake only" in captured.err
    assert not (tmp_path / "experiments").exists()


def test_headless_experiment_requires_fake_model_namespace_before_running(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README.",
            "fake_model_outputs": ["<final>unused</final>"],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-bad-model",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": "Read README.",
                    "prompt_sha256": _sha256("Read README."),
                    "provider_id": "fake",
                    "model_id": "deepseek-chat",
                }
            ],
        },
    )

    status = main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(tmp_path / "experiments"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "model_id must start with fake:" in captured.err
    assert not (tmp_path / "experiments").exists()


def test_headless_experiment_rejects_mismatched_candidate_prompt_hash_before_running(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README.",
            "fake_model_outputs": ["<final>unused</final>"],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-bad-identity",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": "Read README.",
                    "prompt_sha256": _sha256("different prompt"),
                }
            ],
        },
    )

    status = main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(tmp_path / "experiments"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "prompt_sha256 does not match prompt" in captured.err
    assert not (tmp_path / "experiments").exists()


def test_headless_experiment_does_not_mark_finished_before_artifacts_are_written(
    tmp_path, monkeypatch
):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: experiment-alpha\n", encoding="utf-8")
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README and answer with the project fact.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is experiment-alpha.</final>",
            ],
            "verifier": _python_check(
                "os.environ.get('PICO_FINAL_ANSWER') == 'The project fact is experiment-alpha.'"
            ),
            "allowed_tools": ["read_file"],
            "max_steps": 4,
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-smoke",
            "task": str(task_spec),
        },
    )
    spec = load_headless_experiment_spec(experiment_spec)
    runner = HeadlessExperimentRunner(tmp_path / "experiments")

    def fail_export(*args, **kwargs):
        raise OSError("simulated export write failure")

    monkeypatch.setattr(runner.store, "write_experiment_export", fail_export)

    try:
        runner.run(spec)
    except OSError as exc:
        assert "simulated export write failure" in str(exc)
    else:
        raise AssertionError("expected export write failure")

    experiment_dirs = list((tmp_path / "experiments").glob("experiment_runtime-lab-smoke_*"))
    assert len(experiment_dirs) == 1
    wal_events = [
        json.loads(line)["event"]
        for line in (experiment_dirs[0] / "experiment_wal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "artifact_captured" in wal_events
    assert "experiment_finished" not in wal_events
