import json
import os
import subprocess
import sys


def test_write_picobench_run_manifest_redacts_provider_config(tmp_path):
    output_dir = tmp_path / "run"
    evidence_dir = output_dir / "evidence" / "core_001-run1"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "report.json").write_text("{}", encoding="utf-8")
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "suite": "core",
                "benchmark_suite": "picobench-core",
                "provider": "deepseek",
                "model": "deepseek-test",
                "task_count": 1,
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PICO_DEEPSEEK_API_KEY": "secret-value",
        "PICO_DEEPSEEK_API_BASE": "https://api.deepseek.com/anthropic",
        "PICO_DEEPSEEK_MODEL": "deepseek-test",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/write_picobench_run_manifest.py",
            "--output-dir",
            str(output_dir),
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--approval",
            "auto",
            "--sandbox",
            "best_effort",
        ],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    provider = json.loads((output_dir / "provider_config_redacted.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["suite"] == "core"
    assert manifest["benchmark"] == "benchmarks/picobench-core-v1.yaml"
    assert manifest["task_count"] == 1
    assert manifest["evidence_paths"] == ["evidence/core_001-run1"]
    assert provider == {
        "provider": "deepseek",
        "protocol": "anthropic",
        "model": "deepseek-test",
        "base_url_host": "api.deepseek.com",
        "has_api_key": True,
    }
    assert "secret-value" not in (output_dir / "provider_config_redacted.json").read_text(encoding="utf-8")
