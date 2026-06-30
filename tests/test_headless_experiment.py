import json
import hashlib
import shlex
import sys

import pico.headless as headless
from pico.providers.clients import FakeModelClient
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


def _read_experiment_wal(experiment_dir):
    return [
        json.loads(line)
        for line in (experiment_dir / "experiment_wal.jsonl").read_text(encoding="utf-8").splitlines()
    ]


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
        "skipped": 0,
        "reused": 0,
        "scored_runs": 1,
        "benchmark_pass_rate": 1.0,
        "status_counts": {"pass": 1},
        "failure_kind_counts": {},
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
    assert task["boundaries"]["verifier_visible_to_runtime"] is False
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


def test_headless_experiment_counts_only_verifier_failure_as_benchmark_failure(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "verifier_fail",
            "workspace": str(fixture),
            "prompt": "Answer with PASS.",
            "fake_model_outputs": ["<final>PASS according to the agent.</final>"],
            "verifier": _python_check("False"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-verifier-fail",
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

    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["summary"]["passed"] == 0
    assert payload["summary"]["benchmark_failed"] == 1
    assert payload["summary"]["infrastructure_failed"] == 0
    assert payload["summary"]["scored_runs"] == 1
    assert payload["summary"]["benchmark_pass_rate"] == 0.0
    task = payload["task_run"]
    assert task["status"] == "fail"
    assert task["failure_kind"] == "benchmark"
    assert task["failure_category"] == "verifier_failed"
    assert task["runtime"]["status"] == "completed"
    assert task["verifier"]["status"] == "fail"
    assert task["boundaries"]["verifier_visible_to_runtime"] is False


def test_headless_experiment_classifies_provider_failure_as_infrastructure(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "provider_fail",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": [],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-provider-fail",
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
    payload = json.loads(captured.out)
    assert status == 1
    assert payload["summary"]["benchmark_failed"] == 0
    assert payload["summary"]["infrastructure_failed"] == 1
    assert payload["summary"]["scored_runs"] == 0
    assert payload["summary"]["benchmark_pass_rate"] is None
    task = payload["task_run"]
    assert task["status"] == "infra_fail"
    assert task["failure_kind"] == "infrastructure"
    assert task["failure_category"] == "provider_failed"
    assert task["runtime"]["status"] == "failed"
    assert task["runtime"]["terminal_error"]
    assert task["verifier"]["status"] == "skipped"
    assert "provider_error" in captured.err


def test_headless_experiment_classifies_runtime_execution_failure_separately(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "runtime_fail",
            "workspace": str(fixture),
            "prompt": "Try an invalid tool payload.",
            "fake_model_outputs": ["<tool>not json</tool>"],
            "verifier": _python_check("True"),
            "max_steps": 1,
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-runtime-fail",
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

    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    task = payload["task_run"]
    assert task["status"] == "infra_fail"
    assert task["failure_kind"] == "infrastructure"
    assert task["failure_category"] == "runtime_failed"
    assert task["runtime"]["status"] == "failed"
    assert task["runtime"]["terminal_error"]
    assert task["verifier"]["status"] == "skipped"


def test_headless_experiment_classifies_workspace_setup_failure(tmp_path, capsys, monkeypatch):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "setup_fail",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-setup-fail",
            "task": str(task_spec),
        },
    )

    def fail_prepare(self, source_workspace, isolated_workspace):
        raise OSError("workspace copy failed")

    monkeypatch.setattr(headless.HeadlessTaskRunner, "_prepare_workspace", fail_prepare)

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
    payload = json.loads(captured.out)
    assert status == 1
    task = payload["task_run"]
    assert task["status"] == "infra_fail"
    assert task["failure_kind"] == "infrastructure"
    assert task["failure_category"] == "setup_failed"
    assert task["infrastructure_error"] == "workspace copy failed"
    assert task["verifier"]["status"] == "skipped"
    assert "workspace copy failed" in captured.err


def test_headless_experiment_classifies_verifier_timeout_as_infrastructure(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    verifier_code = "import time; time.sleep(2)"
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "verifier_timeout",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": {
                "command": f"{shlex.quote(sys.executable)} -c {shlex.quote(verifier_code)}",
                "timeout_seconds": 1,
            },
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-verifier-timeout",
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
    payload = json.loads(captured.out)
    assert status == 1
    assert payload["summary"]["benchmark_failed"] == 0
    assert payload["summary"]["infrastructure_failed"] == 1
    task = payload["task_run"]
    assert task["status"] == "infra_fail"
    assert task["failure_kind"] == "infrastructure"
    assert task["failure_category"] == "verifier_timeout"
    assert task["runtime"]["status"] == "completed"
    assert task["verifier"]["status"] == "skipped"
    assert task["verifier"]["timed_out"] is True
    assert "verifier timed out" in captured.err


def test_headless_experiment_classifies_artifact_capture_failure_as_infrastructure(
    tmp_path, capsys, monkeypatch
):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "artifact_fail",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": _python_check("False"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-artifact-fail",
            "task": str(task_spec),
        },
    )

    def fail_capture(self, events, *, run_id=None):
        raise headless.ProjectionCaptureError("manifest write failed")

    monkeypatch.setattr(headless.ProjectionManager, "capture", fail_capture)

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
    payload = json.loads(captured.out)
    assert status == 1
    task = payload["task_run"]
    assert task["status"] == "infra_fail"
    assert task["failure_kind"] == "infrastructure"
    assert task["failure_category"] == "runtime_artifact_capture_failed"
    assert task["infrastructure_error"] == "manifest write failed"
    assert task["runtime"]["status"] == "completed"
    assert task["verifier"]["status"] == "skipped"
    assert "manifest write failed" in captured.err


def test_headless_experiment_missing_real_provider_credentials_is_skipped_infrastructure(
    tmp_path, capsys, monkeypatch
):
    for name in (
        "PICO_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "PICO_RIGHT_CODES_API_KEY",
        "RIGHT_CODES_API_KEY",
        "PICO_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README.",
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
                    "provider_id": "openai",
                    "model_id": "gpt-live-acceptance",
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
    assert "missing credentials for provider 'openai'" in captured.err
    payload = json.loads(captured.out)
    assert payload["summary"]["benchmark_failed"] == 0
    assert payload["summary"]["infrastructure_failed"] == 1
    assert payload["summary"]["skipped"] == 1
    assert payload["summary"]["scored_runs"] == 0
    task = payload["task_run"]
    assert task["status"] == "skipped"
    assert task["failure_kind"] == "infrastructure"
    assert task["failure_category"] == "missing_credentials"
    assert task["identity"]["provider_id"] == "openai"
    assert task["identity"]["model_id"] == "gpt-live-acceptance"
    assert task["verifier"]["status"] == "skipped"
    assert task["runtime"]["status"] == "skipped"
    experiment_dir = tmp_path / "experiments" / payload["experiment_run_id"]
    assert (experiment_dir / task["artifacts"]["task_run_export_relpath"]).exists()


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


def test_headless_experiment_requires_real_provider_model_id_before_running(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "Read README.",
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-missing-model",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": "Read README.",
                    "prompt_sha256": _sha256("Read README."),
                    "provider_id": "openai",
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
    assert "provider openai is missing model_id" in captured.err
    assert not (tmp_path / "experiments").exists()


def test_headless_experiment_real_provider_path_preserves_usage_and_cost_metadata(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: live-alpha\n", encoding="utf-8")
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "This task prompt should be replaced by the candidate prompt.",
            "verifier": _python_check(
                "os.environ.get('PICO_FINAL_ANSWER') == 'The project fact is live-alpha.'"
            ),
            "allowed_tools": ["read_file"],
            "max_steps": 4,
        },
    )
    prompt = "Read README and answer with the project fact."
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-real-provider",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-openai",
                    "prompt": prompt,
                    "prompt_sha256": _sha256(prompt),
                    "provider_id": "openai",
                    "model_id": "gpt-live-acceptance",
                }
            ],
        },
    )

    def client_factory(spec):
        assert spec.provider_id == "openai"
        assert spec.model_id == "gpt-live-acceptance"
        return FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is live-alpha.</final>",
            ],
            metadata=[
                {
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "total_tokens": 18,
                    "cached_tokens": 3,
                    "cache_hit": True,
                    "estimated_cost_usd": 0.002,
                },
                {
                    "input_tokens": 13,
                    "output_tokens": 5,
                    "total_tokens": 18,
                    "cached_tokens": 0,
                    "cache_hit": False,
                    "estimated_cost_usd": 0.003,
                },
            ],
        )

    spec = load_headless_experiment_spec(experiment_spec)
    result = HeadlessExperimentRunner(
        tmp_path / "experiments",
        model_client_factory=client_factory,
    ).run(spec)

    assert result.exit_code == 0
    task = result.export["task_run"]
    assert task["identity"]["provider_id"] == "openai"
    assert task["identity"]["model_id"] == "gpt-live-acceptance"
    assert task["status"] == "pass"
    assert task["runtime"]["usage"] == {
        "cache_hits": 1,
        "cache_misses": 1,
        "cached_tokens": 3,
        "input_tokens": 24,
        "output_tokens": 12,
        "total_tokens": 36,
    }
    assert task["runtime"]["cost"] == {"estimated_cost_usd": 0.005}
    experiment_dir = tmp_path / "experiments" / result.export["experiment_run_id"]
    task_export_path = experiment_dir / task["artifacts"]["task_run_export_relpath"]
    task_export = json.loads(task_export_path.read_text(encoding="utf-8"))
    assert task_export["policy"]["model_provider"] == "openai"
    assert task_export["policy"]["model_id"] == "gpt-live-acceptance"
    assert task_export["runtime"]["provider_calls"][0]["metadata"]["estimated_cost_usd"] == 0.002
    assert task_export["runtime"]["provider_calls"][1]["metadata"]["estimated_cost_usd"] == 0.003


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


def test_headless_experiment_resume_reuses_compatible_completed_task(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("project fact: resume-alpha\n", encoding="utf-8")
    prompt = "Read README and answer with the project fact."
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "read_fact",
            "workspace": str(fixture),
            "prompt": "This task prompt should be replaced.",
            "fake_model_outputs": [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is resume-alpha.</final>",
            ],
            "verifier": _python_check(
                "os.environ.get('PICO_FINAL_ANSWER') == 'The project fact is resume-alpha.'"
            ),
            "allowed_tools": ["read_file"],
            "max_steps": 4,
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-resume",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": prompt,
                    "prompt_sha256": _sha256(prompt),
                    "model_id": "fake:resume-model",
                }
            ],
        },
    )

    runs_root = tmp_path / "experiments"
    assert main(["headless", "experiment", "run", str(experiment_spec), "--runs-root", str(runs_root)]) == 0
    first_payload = json.loads(capsys.readouterr().out)
    experiment_dir = runs_root / first_payload["experiment_run_id"]
    first_task_run_id = first_payload["task_run"]["task_run_id"]

    assert main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(runs_root),
            "--resume",
            first_payload["experiment_run_id"],
        ]
    ) == 0
    resumed_payload = json.loads(capsys.readouterr().out)

    assert resumed_payload["experiment_run_id"] == first_payload["experiment_run_id"]
    assert resumed_payload["task_run"]["task_run_id"] == first_task_run_id
    assert resumed_payload["task_run"]["reused"] is True
    assert resumed_payload["summary"]["passed"] == 1
    assert resumed_payload["summary"]["benchmark_failed"] == 0
    assert resumed_payload["summary"]["infrastructure_failed"] == 0
    assert resumed_payload["summary"]["reused"] == 1

    wal_events = _read_experiment_wal(experiment_dir)
    assert [event["event"] for event in wal_events][-3:] == [
        "resume_started",
        "resume_reused_task_run",
        "experiment_finished",
    ]
    assert wal_events[-2]["task_run_id"] == first_task_run_id


def test_headless_experiment_resume_reuses_partial_and_runs_missing_candidate(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    prompt_a = "Answer with alpha."
    prompt_b = "Answer with beta."
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "answer_fact",
            "workspace": str(fixture),
            "prompt": "This task prompt should be replaced.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": _python_check("os.environ.get('PICO_FINAL_ANSWER') == 'ok'"),
        },
    )
    first_spec = _write_json(
        tmp_path / "experiment-first.json",
        {
            "id": "runtime-lab-partial-resume",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": prompt_a,
                    "prompt_sha256": _sha256(prompt_a),
                }
            ],
        },
    )
    second_spec = _write_json(
        tmp_path / "experiment-second.json",
        {
            "id": "runtime-lab-partial-resume",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": prompt_a,
                    "prompt_sha256": _sha256(prompt_a),
                },
                {
                    "id": "candidate-b",
                    "prompt": prompt_b,
                    "prompt_sha256": _sha256(prompt_b),
                },
            ],
        },
    )

    runs_root = tmp_path / "experiments"
    assert main(["headless", "experiment", "run", str(first_spec), "--runs-root", str(runs_root)]) == 0
    first_payload = json.loads(capsys.readouterr().out)
    experiment_dir = runs_root / first_payload["experiment_run_id"]

    assert main(
        [
            "headless",
            "experiment",
            "run",
            str(second_spec),
            "--runs-root",
            str(runs_root),
            "--resume",
            str(experiment_dir),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["summary"]["total_runs"] == 2
    assert payload["summary"]["passed"] == 2
    assert payload["summary"]["reused"] == 1
    assert {row["identity"]["candidate_id"] for row in payload["task_runs"]} == {"candidate-a", "candidate-b"}
    assert [row["reused"] for row in payload["task_runs"] if row["identity"]["candidate_id"] == "candidate-a"] == [True]

    wal_events = _read_experiment_wal(experiment_dir)
    assert any(event["event"] == "resume_reused_task_run" and event["candidate_id"] == "candidate-a" for event in wal_events)
    assert any(event["event"] == "resume_rerun_required" and event["candidate_id"] == "candidate-b" for event in wal_events)


def test_headless_experiment_resume_reruns_prompt_mismatch_with_wal_diagnostic(tmp_path, capsys):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    first_prompt = "Answer with alpha."
    second_prompt = "Answer with beta."
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "answer_fact",
            "workspace": str(fixture),
            "prompt": "This task prompt should be replaced.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": _python_check("os.environ.get('PICO_FINAL_ANSWER') == 'ok'"),
        },
    )
    first_spec = _write_json(
        tmp_path / "experiment-first.json",
        {
            "id": "runtime-lab-rerun",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": first_prompt,
                    "prompt_sha256": _sha256(first_prompt),
                }
            ],
        },
    )
    second_spec = _write_json(
        tmp_path / "experiment-second.json",
        {
            "id": "runtime-lab-rerun",
            "task": str(task_spec),
            "candidates": [
                {
                    "id": "candidate-a",
                    "prompt": second_prompt,
                    "prompt_sha256": _sha256(second_prompt),
                }
            ],
        },
    )

    runs_root = tmp_path / "experiments"
    assert main(["headless", "experiment", "run", str(first_spec), "--runs-root", str(runs_root)]) == 0
    first_payload = json.loads(capsys.readouterr().out)
    experiment_dir = runs_root / first_payload["experiment_run_id"]

    assert main(
        [
            "headless",
            "experiment",
            "run",
            str(second_spec),
            "--runs-root",
            str(runs_root),
            "--resume",
            first_payload["experiment_run_id"],
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["task_run"]["task_run_id"] != first_payload["task_run"]["task_run_id"]
    assert payload["task_run"].get("reused") is not True
    assert payload["summary"]["passed"] == 1
    assert payload["summary"]["reused"] == 0
    wal_events = _read_experiment_wal(experiment_dir)
    rerun_event = [event for event in wal_events if event["event"] == "resume_rerun_required"][-1]
    assert rerun_event["candidate_id"] == "candidate-a"
    assert rerun_event["prompt_sha256"] == _sha256(second_prompt)


def test_headless_experiment_resume_missing_referenced_artifact_is_reconcile_failure(
    tmp_path, capsys
):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "answer_fact",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-missing-artifact",
            "task": str(task_spec),
        },
    )

    runs_root = tmp_path / "experiments"
    assert main(["headless", "experiment", "run", str(experiment_spec), "--runs-root", str(runs_root)]) == 0
    first_payload = json.loads(capsys.readouterr().out)
    experiment_dir = runs_root / first_payload["experiment_run_id"]
    (experiment_dir / first_payload["task_run"]["artifacts"]["runtime_manifest_relpath"]).unlink()

    assert main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(runs_root),
            "--resume",
            str(experiment_dir),
        ]
    ) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["summary"]["benchmark_failed"] == 0
    assert payload["summary"]["infrastructure_failed"] == 1
    assert payload["task_run"]["failure_kind"] == "infrastructure"
    assert payload["task_run"]["failure_category"] == "reconcile_failed"
    assert "runtime_manifest_relpath is missing" in payload["task_run"]["infrastructure_error"]
    assert any(event["event"] == "resume_rejected" for event in _read_experiment_wal(experiment_dir))


def test_headless_experiment_resume_rejects_wal_artifact_summary_disagreement(
    tmp_path, capsys
):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "answer_fact",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-summary-drift",
            "task": str(task_spec),
        },
    )

    runs_root = tmp_path / "experiments"
    assert main(["headless", "experiment", "run", str(experiment_spec), "--runs-root", str(runs_root)]) == 0
    first_payload = json.loads(capsys.readouterr().out)
    experiment_dir = runs_root / first_payload["experiment_run_id"]
    export_path = experiment_dir / "experiment_export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["summary"]["passed"] = 0
    export_path.write_text(json.dumps(export), encoding="utf-8")

    assert main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(runs_root),
            "--resume",
            first_payload["experiment_run_id"],
        ]
    ) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["summary"]["benchmark_failed"] == 0
    assert payload["summary"]["infrastructure_failed"] == 1
    assert payload["task_run"]["failure_category"] == "reconcile_failed"
    assert "summary disagrees" in payload["task_run"]["infrastructure_error"]


def test_headless_experiment_resume_rejects_obsolete_runtime_event_schema(
    tmp_path, capsys
):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    task_spec = _write_json(
        tmp_path / "task.json",
        {
            "id": "answer_fact",
            "workspace": str(fixture),
            "prompt": "Answer directly.",
            "fake_model_outputs": ["<final>ok</final>"],
            "verifier": _python_check("True"),
        },
    )
    experiment_spec = _write_json(
        tmp_path / "experiment.json",
        {
            "id": "runtime-lab-obsolete-schema",
            "task": str(task_spec),
        },
    )

    runs_root = tmp_path / "experiments"
    assert main(["headless", "experiment", "run", str(experiment_spec), "--runs-root", str(runs_root)]) == 0
    first_payload = json.loads(capsys.readouterr().out)
    experiment_dir = runs_root / first_payload["experiment_run_id"]
    task_run = first_payload["task_run"]

    manifest_path = experiment_dir / task_run["artifacts"]["runtime_manifest_relpath"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_event_schema_version"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    task_export_path = experiment_dir / task_run["artifacts"]["task_run_export_relpath"]
    task_export = json.loads(task_export_path.read_text(encoding="utf-8"))
    task_export["runtime"]["runtime_event_schema_version"] = 1
    task_export_path.write_text(json.dumps(task_export), encoding="utf-8")

    wal_path = experiment_dir / "experiment_wal.jsonl"
    wal_events = _read_experiment_wal(experiment_dir)
    for event in wal_events:
        if event["event"] == "artifact_captured":
            event["runtime_event_schema_version"] = 1
    wal_path.write_text("\n".join(json.dumps(event) for event in wal_events) + "\n", encoding="utf-8")

    assert main(
        [
            "headless",
            "experiment",
            "run",
            str(experiment_spec),
            "--runs-root",
            str(runs_root),
            "--resume",
            first_payload["experiment_run_id"],
        ]
    ) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["summary"]["benchmark_failed"] == 0
    assert payload["summary"]["infrastructure_failed"] == 1
    assert payload["task_run"]["failure_category"] == "reconcile_failed"
    assert "runtime schema version is incompatible" in payload["task_run"]["infrastructure_error"]
