import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ablation_plan_writes_public_cli_feature_flag_variants(tmp_path):
    output_dir = tmp_path / "ablation"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_ablation.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--suite",
            "core",
            "--output-dir",
            str(output_dir),
            "--plan-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((output_dir / "ablation_summary.json").read_text(encoding="utf-8"))
    assert [row["variant"] for row in summary["variants"]] == [
        "pico-full",
        "pico-no-memory",
        "pico-no-plan",
        "pico-no-subagent",
        "pico-no-skills",
    ]
    assert all(row["status"] == "planned" for row in summary["variants"])
    assert summary["planned_only"] is True
    args_by_variant = {row["variant"]: row["pico_args"] for row in summary["variants"]}
    assert args_by_variant["pico-full"] == []
    assert args_by_variant["pico-no-memory"] == ["--disable-memory"]
    assert args_by_variant["pico-no-plan"] == ["--disable-plan-mode"]
    assert args_by_variant["pico-no-subagent"] == ["--disable-subagents"]
    assert args_by_variant["pico-no-skills"] == ["--disable-skills"]
    markdown = (output_dir / "ablation_summary.md").read_text(encoding="utf-8")
    assert "# PicoBench 消融汇总" in markdown
    assert "已规划" in markdown


def test_ablation_run_invokes_each_variant_with_feature_flags(tmp_path):
    output_dir = tmp_path / "ablation-run"
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        """
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", required=True)
parser.add_argument("--benchmark")
parser.add_argument("--suite")
parser.add_argument("--approval")
parser.add_argument("--sandbox")
parser.add_argument("--runs")
parser.add_argument("--pico-command")
parser.add_argument("--json", action="store_true")
parser.add_argument("--task", action="append", default=[])
parser.add_argument("--disable-memory", action="store_true")
parser.add_argument("--disable-plan-mode", action="store_true")
parser.add_argument("--disable-subagents", action="store_true")
parser.add_argument("--disable-skills", action="store_true")
args, _ = parser.parse_known_args()
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
summary = {
    "task_count": 1,
    "strict_failed": 0,
    "strict_pass_rate": 1.0,
    "functional_pass_rate": 1.0,
    "safety_violation_rate": 0.0,
    "evidence_consistency_rate": 1.0,
    "avg_tool_steps": 2.0,
    "avg_cost_usd": 0.0,
    "duration_ms_p50": 10.0,
    "failure_category_counts": {},
}
(output_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
print(json.dumps({"output_dir": str(output_dir)}))
""".lstrip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_ablation.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--suite",
            "core",
            "--task",
            "core_001",
            "--output-dir",
            str(output_dir),
            "--runner-script",
            str(fake_runner),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((output_dir / "ablation_summary.json").read_text(encoding="utf-8"))
    assert summary["planned_only"] is False
    assert all(row["status"] == "completed" for row in summary["variants"])
    command_by_variant = {row["variant"]: row["command"] for row in summary["variants"]}
    assert "--disable-memory" in command_by_variant["pico-no-memory"]
    assert "--disable-plan-mode" in command_by_variant["pico-no-plan"]
    assert "--disable-subagents" in command_by_variant["pico-no-subagent"]
    assert "--disable-skills" in command_by_variant["pico-no-skills"]
    assert "--task" in command_by_variant["pico-full"]
    assert summary["variants"][0]["metrics"]["solve@1_strict"] == 1.0


def test_ablation_plan_expands_task_list(tmp_path):
    output_dir = tmp_path / "ablation-task-list"
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("core_001\n# retry after provider recovery\ncore_056\ncore_001\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_ablation.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--suite",
            "core",
            "--task-list",
            str(task_list),
            "--output-dir",
            str(output_dir),
            "--plan-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((output_dir / "ablation_summary.json").read_text(encoding="utf-8"))
    command = summary["variants"][0]["command"]
    assert command.count("--task") == 2
    assert "core_001" in command
    assert "core_056" in command


def test_ablation_run_marks_provider_balance_blocker(tmp_path):
    output_dir = tmp_path / "ablation-provider-blocked"
    fake_runner = tmp_path / "fake_provider_blocked_runner.py"
    fake_runner.write_text(
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
    "strict_pass_rate": 0.0,
    "functional_pass_rate": 0.0,
    "safety_violation_rate": 0.0,
    "evidence_consistency_rate": 1.0,
    "avg_tool_steps": 0.0,
    "avg_cost_usd": 0.0,
    "duration_ms_p50": 10.0,
    "failure_category_counts": {"provider_insufficient_balance": 1},
}
(output_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
print(json.dumps({"output_dir": str(output_dir)}))
sys.exit(1)
""".lstrip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_ablation.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--suite",
            "core",
            "--task",
            "core_056",
            "--output-dir",
            str(output_dir),
            "--runner-script",
            str(fake_runner),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    summary = json.loads((output_dir / "ablation_summary.json").read_text(encoding="utf-8"))
    assert {row["status"] for row in summary["variants"]} == {"provider_blocked"}
    assert all(row["status_label"] == "Provider 余额不足" for row in summary["variants"])
    markdown = (output_dir / "ablation_summary.md").read_text(encoding="utf-8")
    assert "Provider 余额不足" in markdown
