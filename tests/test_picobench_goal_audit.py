import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_goal_audit_passes_when_live_and_ablation_are_complete(tmp_path):
    branch = _current_branch()
    live_dir = tmp_path / "live"
    ablation_dir = tmp_path / "ablation"
    _write_live_summary(live_dir, strict_failed=0, failure_counts={})
    _write_ablation_summary(ablation_dir, "completed")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_picobench_goal.py",
            "--live-output-dir",
            str(live_dir),
            "--ablation-output-dir",
            str(ablation_dir),
            "--expected-branch",
            branch,
            "--output-dir",
            str(tmp_path / "audit"),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["completed"] is True
    assert payload["status"] == "completed"
    markdown = (tmp_path / "audit" / "goal_audit.md").read_text(encoding="utf-8")
    assert "PicoBench DeepSeek 目标审计" in markdown
    assert "已完成" in markdown


def test_goal_audit_reports_provider_blocker(tmp_path):
    branch = _current_branch()
    live_dir = tmp_path / "live-blocked"
    ablation_dir = tmp_path / "ablation-blocked"
    _write_live_summary(live_dir, strict_failed=45, failure_counts={"provider_insufficient_balance": 45})
    _write_ablation_summary(ablation_dir, "provider_blocked")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_picobench_goal.py",
            "--live-output-dir",
            str(live_dir),
            "--ablation-output-dir",
            str(ablation_dir),
            "--expected-branch",
            branch,
            "--output-dir",
            str(tmp_path / "audit-blocked"),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["completed"] is False
    assert payload["status"] == "provider_blocked"
    assert payload["blocking_reason"] == "DeepSeek provider 余额不足"
    audit = json.loads((tmp_path / "audit-blocked" / "goal_audit.json").read_text(encoding="utf-8"))
    live_row = next(row for row in audit["requirements"] if row["id"] == "deepseek_live_100")
    assert live_row["status"] == "provider_blocked"
    assert live_row["details"]["deepseek_command_count"] == 100


def test_goal_audit_reports_provider_network_blocker(tmp_path):
    branch = _current_branch()
    live_dir = tmp_path / "live-network-blocked"
    ablation_dir = tmp_path / "ablation-complete"
    _write_live_summary(live_dir, strict_failed=29, failure_counts={"provider_network_error": 29})
    _write_ablation_summary(ablation_dir, "completed")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_picobench_goal.py",
            "--live-output-dir",
            str(live_dir),
            "--ablation-output-dir",
            str(ablation_dir),
            "--expected-branch",
            branch,
            "--output-dir",
            str(tmp_path / "audit-network-blocked"),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["completed"] is False
    assert payload["status"] == "provider_blocked"
    assert "DeepSeek provider 网络错误" in payload["blocking_reason"]


def test_goal_audit_rejects_summary_without_per_task_deepseek_command(tmp_path):
    branch = _current_branch()
    live_dir = tmp_path / "live-no-provider-command"
    ablation_dir = tmp_path / "ablation-complete"
    _write_live_summary(live_dir, strict_failed=0, failure_counts={}, include_provider_command=False)
    _write_ablation_summary(ablation_dir, "completed")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_picobench_goal.py",
            "--live-output-dir",
            str(live_dir),
            "--ablation-output-dir",
            str(ablation_dir),
            "--expected-branch",
            branch,
            "--output-dir",
            str(tmp_path / "audit-no-provider-command"),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["status"] == "incomplete"
    audit = json.loads((tmp_path / "audit-no-provider-command" / "goal_audit.json").read_text(encoding="utf-8"))
    live_row = next(row for row in audit["requirements"] if row["id"] == "deepseek_live_100")
    assert live_row["details"]["deepseek_command_count"] == 0
    assert len(live_row["details"]["missing_deepseek_command_tasks"]) == 100


def test_goal_audit_rejects_wrong_task_id_set_even_with_100_results(tmp_path):
    branch = _current_branch()
    live_dir = tmp_path / "live-wrong-task-set"
    ablation_dir = tmp_path / "ablation-complete"
    _write_live_summary(live_dir, strict_failed=0, failure_counts={}, task_ids=[f"core_{index:03d}" for index in range(2, 102)])
    _write_ablation_summary(ablation_dir, "completed")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_picobench_goal.py",
            "--live-output-dir",
            str(live_dir),
            "--ablation-output-dir",
            str(ablation_dir),
            "--expected-branch",
            branch,
            "--output-dir",
            str(tmp_path / "audit-wrong-task-set"),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["status"] == "incomplete"
    audit = json.loads((tmp_path / "audit-wrong-task-set" / "goal_audit.json").read_text(encoding="utf-8"))
    live_row = next(row for row in audit["requirements"] if row["id"] == "deepseek_live_100")
    assert live_row["details"]["missing_expected_task_ids"] == ["core_001"]
    assert live_row["details"]["unexpected_task_ids"] == ["core_101"]


def test_goal_audit_records_merge_manifest_details(tmp_path):
    branch = _current_branch()
    live_dir = tmp_path / "merged-live"
    ablation_dir = tmp_path / "ablation-complete"
    _write_live_summary(live_dir, strict_failed=0, failure_counts={})
    (live_dir / "merge_manifest.json").write_text(
        json.dumps(
            {
                "task_count": 100,
                "replaced_task_count": 2,
                "replaced_tasks": ["core_056", "core_057"],
                "sources": [{"input_dir": "/tmp/full"}, {"input_dir": "/tmp/retry"}],
            }
        ),
        encoding="utf-8",
    )
    _write_ablation_summary(ablation_dir, "completed")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/audit_picobench_goal.py",
            "--live-output-dir",
            str(live_dir),
            "--ablation-output-dir",
            str(ablation_dir),
            "--expected-branch",
            branch,
            "--output-dir",
            str(tmp_path / "audit-merged-live"),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    audit = json.loads((tmp_path / "audit-merged-live" / "goal_audit.json").read_text(encoding="utf-8"))
    live_row = next(row for row in audit["requirements"] if row["id"] == "deepseek_live_100")
    assert live_row["details"]["merge"]["present"] is True
    assert live_row["details"]["merge"]["task_count"] == 100
    assert live_row["details"]["merge"]["replaced_task_count"] == 2
    assert live_row["details"]["merge"]["source_count"] == 2


def _current_branch() -> str:
    completed = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def _write_live_summary(
    path: Path,
    *,
    strict_failed: int,
    failure_counts: dict,
    include_provider_command: bool = True,
    task_ids: list[str] | None = None,
):
    path.mkdir(parents=True)
    task_ids = task_ids or [f"core_{index:03d}" for index in range(1, 101)]
    strict_passed = 100 - strict_failed
    results = [
        {
            "task_id": task_id,
            "category": "harness",
            "strict_pass": index <= strict_passed,
            "failure_category": None if index <= strict_passed else next(iter(failure_counts or {"runner_error": 1})),
            "command": {
                "command": ["uv", "run", "pico", "--provider", "deepseek", "fix"]
                if include_provider_command
                else ["uv", "run", "pico", "fix"]
            },
            "checks": [],
            "report": {},
        }
        for index, task_id in enumerate(task_ids, start=1)
    ]
    summary = {
        "suite": "core",
        "provider": "deepseek",
        "task_count": 100,
        "strict_passed": strict_passed,
        "strict_failed": strict_failed,
        "failure_category_counts": failure_counts,
        "results": results,
    }
    (path / "summary_reclassified.json").write_text(json.dumps(summary), encoding="utf-8")


def _write_ablation_summary(path: Path, status: str):
    path.mkdir(parents=True)
    variants = ["pico-full", "pico-no-memory", "pico-no-plan", "pico-no-subagent", "pico-no-skills"]
    summary = {
        "mode": "run",
        "planned_only": False,
        "variants": [
            {
                "variant": variant,
                "status": status,
                "metrics": {
                    "failure_category_counts": {} if status == "completed" else {"provider_insufficient_balance": 1},
                },
            }
            for variant in variants
        ],
    }
    (path / "ablation_summary.json").write_text(json.dumps(summary), encoding="utf-8")
