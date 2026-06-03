import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_goal_live_orchestrator_runs_all_steps_when_live_returns_nonzero(tmp_path):
    live_runner = tmp_path / "fake_live_runner.py"
    reclassify = tmp_path / "fake_reclassify.py"
    ablation = tmp_path / "fake_ablation.py"
    audit = tmp_path / "fake_audit.py"
    _write_fake_live_runner(live_runner)
    _write_fake_reclassify(reclassify)
    _write_fake_ablation(ablation)
    _write_fake_audit(audit)

    output_dir = tmp_path / "goal-live"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--output-dir",
            str(output_dir),
            "--runner-script",
            str(live_runner),
            "--reclassify-script",
            str(reclassify),
            "--ablation-script",
            str(ablation),
            "--audit-script",
            str(audit),
            "--max-steps",
            "2",
            "--timeout-sec",
            "30",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    manifest = json.loads((output_dir / "goal_live_run.json").read_text(encoding="utf-8"))
    assert [step["name"] for step in manifest["steps"]] == ["live", "reclassify", "ablation", "audit"]
    assert manifest["steps"][0]["returncode"] == 1
    assert manifest["steps"][1]["returncode"] == 0
    assert manifest["steps"][2]["returncode"] == 0
    assert manifest["steps"][3]["returncode"] == 1
    assert manifest["status"] == "provider_blocked"
    live_command = manifest["steps"][0]["command"]
    assert "--provider" in live_command
    assert "deepseek" in live_command
    assert "--max-steps" in live_command
    assert "--timeout-sec" in live_command
    assert (output_dir / "goal_live_run.md").is_file()


def test_goal_live_orchestrator_passes_task_list_to_live_and_ablation(tmp_path):
    live_runner = tmp_path / "fake_live_runner.py"
    reclassify = tmp_path / "fake_reclassify.py"
    ablation = tmp_path / "fake_ablation.py"
    audit = tmp_path / "fake_audit.py"
    _write_fake_live_runner(live_runner)
    _write_fake_reclassify(reclassify)
    _write_fake_ablation(ablation)
    _write_fake_audit(audit)
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("core_056\ncore_057\n", encoding="utf-8")

    output_dir = tmp_path / "goal-live-task-list"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--output-dir",
            str(output_dir),
            "--task-list",
            str(task_list),
            "--runner-script",
            str(live_runner),
            "--reclassify-script",
            str(reclassify),
            "--ablation-script",
            str(ablation),
            "--audit-script",
            str(audit),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    manifest = json.loads((output_dir / "goal_live_run.json").read_text(encoding="utf-8"))
    live_command = next(step for step in manifest["steps"] if step["name"] == "live")["command"]
    ablation_command = next(step for step in manifest["steps"] if step["name"] == "ablation")["command"]
    assert "--task-list" in live_command
    assert str(task_list) in live_command
    assert "--task-list" in ablation_command
    assert str(task_list) in ablation_command


def test_goal_live_orchestrator_merges_previous_full_with_retry_output(tmp_path):
    live_runner = tmp_path / "fake_live_runner.py"
    reclassify = tmp_path / "fake_reclassify.py"
    merge = tmp_path / "fake_merge.py"
    ablation = tmp_path / "fake_ablation.py"
    audit = tmp_path / "fake_audit.py"
    _write_fake_live_runner(live_runner)
    _write_fake_reclassify(reclassify)
    _write_fake_merge(merge)
    _write_fake_ablation(ablation)
    _write_fake_audit(audit)
    previous = tmp_path / "previous-full"
    previous.mkdir()
    (previous / "summary_reclassified.json").write_text(json.dumps({"results": []}), encoding="utf-8")

    output_dir = tmp_path / "goal-live-merge"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--output-dir",
            str(output_dir),
            "--merge-source-dir",
            str(previous),
            "--runner-script",
            str(live_runner),
            "--reclassify-script",
            str(reclassify),
            "--merge-script",
            str(merge),
            "--ablation-script",
            str(ablation),
            "--audit-script",
            str(audit),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    manifest = json.loads((output_dir / "goal_live_run.json").read_text(encoding="utf-8"))
    assert [step["name"] for step in manifest["steps"]] == ["live", "reclassify", "merge", "ablation", "audit"]
    merge_command = next(step for step in manifest["steps"] if step["name"] == "merge")["command"]
    assert str(previous) in merge_command
    assert str(output_dir / "live") in merge_command
    audit_command = next(step for step in manifest["steps"] if step["name"] == "audit")["command"]
    assert str(output_dir / "merged-live") in audit_command


def test_goal_live_retry_from_output_dir_adds_task_list_and_merge_source(tmp_path):
    live_runner = tmp_path / "fake_live_runner.py"
    reclassify = tmp_path / "fake_reclassify.py"
    merge = tmp_path / "fake_merge.py"
    ablation = tmp_path / "fake_ablation.py"
    audit = tmp_path / "fake_audit.py"
    _write_fake_live_runner(live_runner)
    _write_fake_reclassify(reclassify)
    _write_fake_merge(merge)
    _write_fake_ablation(ablation)
    _write_fake_audit(audit)
    previous = tmp_path / "previous-full"
    previous.mkdir()
    (previous / "summary_reclassified.json").write_text(json.dumps({"results": []}), encoding="utf-8")
    (previous / "retry_tasks.txt").write_text("core_056\ncore_057\n", encoding="utf-8")

    output_dir = tmp_path / "goal-live-retry-from"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--output-dir",
            str(output_dir),
            "--retry-from-output-dir",
            str(previous),
            "--runner-script",
            str(live_runner),
            "--reclassify-script",
            str(reclassify),
            "--merge-script",
            str(merge),
            "--ablation-script",
            str(ablation),
            "--audit-script",
            str(audit),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    manifest = json.loads((output_dir / "goal_live_run.json").read_text(encoding="utf-8"))
    live_command = next(step for step in manifest["steps"] if step["name"] == "live")["command"]
    merge_command = next(step for step in manifest["steps"] if step["name"] == "merge")["command"]
    assert "--task-list" in live_command
    assert str(previous / "retry_tasks.txt") in live_command
    assert str(previous) in merge_command


def test_goal_live_retry_from_output_dir_requires_retry_tasks(tmp_path):
    previous = tmp_path / "previous-full"
    previous.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--output-dir",
            str(tmp_path / "goal-live-missing-retry"),
            "--retry-from-output-dir",
            str(previous),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    assert "找不到 retry_tasks.txt" in completed.stderr


def test_goal_live_orchestrator_rejects_repo_output_dir():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--output-dir",
            str(ROOT / "tmp-goal-live"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    assert "闭环输出目录必须在 Pico repo 之外，或 _local/benchmark/runs 下" in completed.stderr


def test_goal_live_orchestrator_status_uses_audit_stdout(tmp_path):
    live_runner = tmp_path / "fake_live_runner.py"
    reclassify = tmp_path / "fake_reclassify.py"
    ablation = tmp_path / "fake_ablation.py"
    audit = tmp_path / "fake_incomplete_audit.py"
    _write_fake_live_runner(live_runner)
    _write_fake_reclassify(reclassify)
    _write_fake_ablation(ablation)
    _write_fake_audit(audit, status="incomplete")

    output_dir = tmp_path / "goal-live-incomplete"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--output-dir",
            str(output_dir),
            "--runner-script",
            str(live_runner),
            "--reclassify-script",
            str(reclassify),
            "--ablation-script",
            str(ablation),
            "--audit-script",
            str(audit),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    assert json.loads((output_dir / "goal_live_run.json").read_text(encoding="utf-8"))["status"] == "incomplete"


def test_goal_live_preflight_provider_block_short_circuits(tmp_path):
    live_runner = tmp_path / "fake_preflight_blocked_runner.py"
    _write_fake_provider_blocked_runner(live_runner)

    output_dir = tmp_path / "goal-live-preflight-blocked"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--output-dir",
            str(output_dir),
            "--preflight-task",
            "core_056",
            "--runner-script",
            str(live_runner),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    manifest = json.loads((output_dir / "goal_live_run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "provider_blocked"
    assert [step["name"] for step in manifest["steps"]] == ["preflight", "live", "reclassify", "ablation"]
    preflight_command = manifest["steps"][0]["command"]
    assert "--task" in preflight_command
    assert "core_056" in preflight_command
    assert "--task-list" not in preflight_command
    assert manifest["steps"][1]["status"] == "skipped"
    assert not (output_dir / "live").exists()


def test_goal_live_preflight_can_override_step_limits_without_changing_live(tmp_path):
    live_runner = tmp_path / "fake_live_runner.py"
    reclassify = tmp_path / "fake_reclassify.py"
    ablation = tmp_path / "fake_ablation.py"
    audit = tmp_path / "fake_audit.py"
    _write_fake_live_runner(live_runner)
    _write_fake_reclassify(reclassify)
    _write_fake_ablation(ablation)
    _write_fake_audit(audit)

    output_dir = tmp_path / "goal-live-preflight-limits"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_goal_live.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--output-dir",
            str(output_dir),
            "--preflight-task",
            "core_056",
            "--preflight-max-steps",
            "2",
            "--preflight-timeout-sec",
            "30",
            "--max-steps",
            "12",
            "--timeout-sec",
            "300",
            "--runner-script",
            str(live_runner),
            "--reclassify-script",
            str(reclassify),
            "--ablation-script",
            str(ablation),
            "--audit-script",
            str(audit),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    manifest = json.loads((output_dir / "goal_live_run.json").read_text(encoding="utf-8"))
    preflight_command = next(step for step in manifest["steps"] if step["name"] == "preflight")["command"]
    live_command = next(step for step in manifest["steps"] if step["name"] == "live")["command"]
    assert preflight_command[preflight_command.index("--max-steps") + 1] == "2"
    assert preflight_command[preflight_command.index("--timeout-sec") + 1] == "30"
    assert live_command[live_command.index("--max-steps") + 1] == "12"
    assert live_command[live_command.index("--timeout-sec") + 1] == "300"


def _write_fake_live_runner(path: Path) -> None:
    path.write_text(
        """
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
args, _ = parser.parse_known_args()
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "summary.json").write_text(json.dumps({"results": []}), encoding="utf-8")
print(json.dumps({"output_dir": str(output_dir)}))
sys.exit(1)
""".lstrip(),
        encoding="utf-8",
    )


def _write_fake_provider_blocked_runner(path: Path) -> None:
    path.write_text(
        """
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
args, _ = parser.parse_known_args()
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
summary = {
    "task_count": 1,
    "strict_failed": 1,
    "failure_category_counts": {"provider_insufficient_balance": 1},
    "results": [],
}
(output_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
print(json.dumps({"output_dir": str(output_dir)}))
sys.exit(1)
""".lstrip(),
        encoding="utf-8",
    )


def _write_fake_reclassify(path: Path) -> None:
    path.write_text(
        """
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", required=True)
args = parser.parse_args()
input_dir = Path(args.input_dir)
(input_dir / "summary_reclassified.json").write_text(json.dumps({"results": []}), encoding="utf-8")
print(json.dumps({"output_dir": str(input_dir)}))
""".lstrip(),
        encoding="utf-8",
    )


def _write_fake_merge(path: Path) -> None:
    path.write_text(
        """
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
parser.add_argument("--input-dir", action="append", default=[])
parser.add_argument("--expected-task-count")
args = parser.parse_args()
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "summary.json").write_text(json.dumps({"results": []}), encoding="utf-8")
(output_dir / "merge_manifest.json").write_text(json.dumps({"input_dirs": args.input_dir}), encoding="utf-8")
print(json.dumps({"output_dir": str(output_dir)}))
""".lstrip(),
        encoding="utf-8",
    )


def _write_fake_ablation(path: Path) -> None:
    path.write_text(
        """
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
args, _ = parser.parse_known_args()
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "ablation_summary.json").write_text(json.dumps({"variants": []}), encoding="utf-8")
print(json.dumps({"output_dir": str(output_dir)}))
""".lstrip(),
        encoding="utf-8",
    )


def _write_fake_audit(path: Path, status: str = "provider_blocked") -> None:
    path.write_text(
        f"""
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
args, _ = parser.parse_known_args()
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "goal_audit.json").write_text(json.dumps({{"status": "{status}"}}), encoding="utf-8")
print(json.dumps({{"status": "{status}"}}))
sys.exit(1)
""".lstrip(),
        encoding="utf-8",
    )
