import json
import subprocess
import sys


def test_retry_failures_dry_run_selects_legacy_insufficient_balance(tmp_path):
    evidence = tmp_path / "out" / "evidence" / "core_056-run1"
    evidence.mkdir(parents=True)
    (evidence / "trace.jsonl").write_text(
        json.dumps({"event": "model_error", "error": {"http_status": 402, "body_excerpt": "Insufficient Balance"}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "summary.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "task_id": "core_056",
                        "strict_pass": False,
                        "failure_category": "model_error",
                        "evidence_path": str(evidence),
                    },
                    {
                        "task_id": "core_057",
                        "strict_pass": False,
                        "failure_category": "hidden_test_failure",
                        "evidence_path": "",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_retry_failures.py",
            "--previous-output-dir",
            str(tmp_path / "out"),
            "--output-dir",
            str(tmp_path / "retry"),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["tasks"] == ["core_056"]


def test_retry_failures_dry_run_selects_provider_network_errors(tmp_path):
    evidence = tmp_path / "out" / "evidence" / "core_072-run1"
    evidence.mkdir(parents=True)
    (evidence / "trace.jsonl").write_text(
        json.dumps({"event": "model_error", "error": {"code": "network_error", "cause_type": "URLError"}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "summary.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "task_id": "core_072",
                        "strict_pass": False,
                        "failure_category": "model_error",
                        "evidence_path": str(evidence),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_retry_failures.py",
            "--previous-output-dir",
            str(tmp_path / "out"),
            "--output-dir",
            str(tmp_path / "retry"),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["failure_categories"] == ["provider_insufficient_balance", "provider_network_error"]
    assert payload["tasks"] == ["core_072"]


def test_retry_failures_task_list_filters_selected_failures(tmp_path):
    evidence = tmp_path / "out" / "evidence" / "core_056-run1"
    evidence.mkdir(parents=True)
    (evidence / "trace.jsonl").write_text(
        json.dumps({"event": "model_error", "error": {"http_status": 402, "body_excerpt": "Insufficient Balance"}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "summary.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "task_id": "core_056",
                        "strict_pass": False,
                        "failure_category": "model_error",
                        "evidence_path": str(evidence),
                    },
                    {
                        "task_id": "core_057",
                        "strict_pass": False,
                        "failure_category": "model_error",
                        "evidence_path": str(evidence),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    task_list = tmp_path / "retry_tasks.txt"
    task_list.write_text("core_057\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_retry_failures.py",
            "--previous-output-dir",
            str(tmp_path / "out"),
            "--output-dir",
            str(tmp_path / "retry"),
            "--task-list",
            str(task_list),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["tasks"] == ["core_057"]


def test_reclassify_failures_writes_retry_task_list(tmp_path):
    evidence = tmp_path / "out" / "evidence" / "core_056-run1"
    evidence.mkdir(parents=True)
    (evidence / "trace.jsonl").write_text(
        json.dumps({"event": "model_error", "error": {"http_status": 402, "body_excerpt": "Insufficient Balance"}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "summary.json").write_text(
        json.dumps(
            {
                "suite": "core",
                "benchmark_suite": "core",
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "pico_commit": "abc123",
                "started_at": "2026-05-29T02:49:00",
                "results": [
                    {
                        "task_id": "core_056",
                        "category": "harness",
                        "strict_pass": False,
                        "failure_category": "model_error",
                        "evidence_path": str(evidence),
                        "checks": [],
                        "report": {},
                    },
                    {
                        "task_id": "core_057",
                        "category": "harness",
                        "strict_pass": False,
                        "failure_category": "hidden_test_failure",
                        "evidence_path": "",
                        "checks": [],
                        "report": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/reclassify_picobench_failures.py",
            "--input-dir",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["failure_category_counts"] == {
        "hidden_test_failure": 1,
        "provider_insufficient_balance": 1,
    }
    assert payload["retry_tasks"] == ["core_056"]
    assert (tmp_path / "out" / "retry_tasks.txt").read_text(encoding="utf-8") == "core_056\n"
