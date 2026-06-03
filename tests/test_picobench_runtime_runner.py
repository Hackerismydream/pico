import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_l0_runtime_runner_runs_legacy_schema_without_public_cli_loader(tmp_path):
    output_dir = tmp_path / "runtime"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench_runtime.py",
            "--benchmark",
            "benchmarks/picobench-runtime-v1.json",
            "--output-dir",
            str(output_dir),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    compact = json.loads(completed.stdout)
    assert compact["summary"]["total_tasks"] == 2
    assert compact["summary"]["failed"] == 0
    artifact = json.loads((output_dir / "runtime_artifact.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in artifact["rows"]] == ["readme_intro_locked", "sample_beta_locked"]


def test_public_picobench_runner_explains_runtime_schema_boundary(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench.py",
            "--benchmark",
            "benchmarks/picobench-runtime-v1.json",
            "--output-dir",
            str(tmp_path / "public"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 2
    assert "L0 deterministic runtime schema" in completed.stderr
    assert "run_picobench_runtime.py" in completed.stderr
