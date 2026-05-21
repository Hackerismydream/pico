import json
import subprocess
import sys


def test_ablation_plan_writes_planned_variants_without_runtime_flags(tmp_path):
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
        cwd="/Users/martinlos/code/pico",
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
