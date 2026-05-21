import json
import subprocess
import sys


def test_run_picobench_smoke_with_fake_public_cli(tmp_path):
    fixture = tmp_path / "fixtures" / "orders_api"
    fixture.mkdir(parents=True)
    (fixture / "README.md").write_text("fixture\n", encoding="utf-8")
    fake_pico = tmp_path / "fake_pico.py"
    fake_pico.write_text(
        """
import json
import pathlib
import sys

args = sys.argv[1:]
workspace = pathlib.Path(args[args.index("--cwd") + 1])
(workspace / "RESULT.txt").write_text("patched\\n", encoding="utf-8")
run_dir = workspace / ".pico" / "runs" / "run_1"
session_dir = workspace / ".pico" / "sessions"
run_dir.mkdir(parents=True, exist_ok=True)
session_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "report.json").write_text(json.dumps({
    "status": "completed",
    "stop_reason": "final_answer_returned",
    "tool_steps": 1,
    "tool_name_counts": {"run_shell": 1},
    "tool_status_counts": {"success": 1},
    "security_event_counts": {},
}), encoding="utf-8")
(run_dir / "task_state.json").write_text(json.dumps({
    "status": "completed",
    "stop_reason": "final_answer_returned",
    "changed_paths": ["RESULT.txt"],
}), encoding="utf-8")
(run_dir / "trace.jsonl").write_text(
    json.dumps({"event": "tool_executed", "name": "run_shell", "tool_status": "success"}) + "\\n"
    + json.dumps({"event": "run_finished", "status": "completed", "stop_reason": "final_answer_returned"}) + "\\n",
    encoding="utf-8",
)
(session_dir / "session.json").write_text("{}", encoding="utf-8")
(session_dir / "session.events.jsonl").write_text("", encoding="utf-8")
print("fake pico ok")
""".strip(),
        encoding="utf-8",
    )
    benchmark = tmp_path / "picobench-core-v1.yaml"
    benchmark.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite": "picobench-core",
                "tasks": [
                    {
                        "task_id": "core_001",
                        "suite": "picobench-core",
                        "category": "bugfix",
                        "repo": {"fixture": "fixtures/orders_api"},
                        "prompt": {"text": "Create RESULT.txt"},
                        "execution": {"driver": "one_shot_cli", "max_steps": 3, "timeout_sec": 30},
                        "tests": {"public": ["python -c \"import pathlib; assert pathlib.Path('RESULT.txt').read_text() == 'patched\\\\n'\""]},
                        "verifiers": [{"type": "evidence"}, {"type": "changed_paths", "any": ["RESULT.txt"]}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench.py",
            "--suite",
            "core",
            "--benchmark",
            str(benchmark),
            "--task",
            "core_001",
            "--output-dir",
            str(output_dir),
            "--pico-command",
            f"{sys.executable} {fake_pico}",
            "--json",
        ],
        cwd="/Users/martinlos/code/pico",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["strict_pass_rate"] == 1.0
    assert (output_dir / "summary.md").is_file()
    assert (output_dir / "task_results.jsonl").is_file()
    assert (output_dir / "evidence" / "core_001-run1" / "report.json").is_file()


def test_run_picobench_repl_driver_sends_prompt_on_stdin(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("fixture\n", encoding="utf-8")
    fake_pico = tmp_path / "fake_repl.py"
    fake_pico.write_text(
        """
import json
import pathlib
import sys

args = sys.argv[1:]
workspace = pathlib.Path(args[args.index("--cwd") + 1])
stdin_text = sys.stdin.read()
(workspace / "argv.json").write_text(json.dumps(args), encoding="utf-8")
(workspace / "stdin.txt").write_text(stdin_text, encoding="utf-8")
run_dir = workspace / ".pico" / "runs" / "run_1"
session_dir = workspace / ".pico" / "sessions"
run_dir.mkdir(parents=True, exist_ok=True)
session_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "report.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "tool_steps": 0}), encoding="utf-8")
(run_dir / "task_state.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "changed_paths": []}), encoding="utf-8")
(run_dir / "trace.jsonl").write_text(json.dumps({"event": "run_finished", "status": "completed", "stop_reason": "final_answer_returned"}) + "\\n", encoding="utf-8")
(session_dir / "session.json").write_text("{}", encoding="utf-8")
(session_dir / "session.events.jsonl").write_text("", encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    benchmark = tmp_path / "benchmark.yaml"
    benchmark.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite": "picobench-agentic",
                "tasks": [
                    {
                        "task_id": "S07",
                        "suite": "picobench-agentic",
                        "category": "cli_behavior",
                        "repo": {"fixture": "fixture"},
                        "prompt": {"text": "/help"},
                        "execution": {"driver": "repl", "max_steps": 3, "timeout_sec": 30},
                        "tests": {"public": ["python -c \"import json, pathlib; args=json.loads(pathlib.Path('argv.json').read_text()); stdin=pathlib.Path('stdin.txt').read_text(); assert '--repl' in args and '/help' in stdin and '/exit' in stdin and '/help' not in args\""]},
                        "verifiers": [{"type": "evidence"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_picobench.py",
            "--suite",
            "agentic",
            "--benchmark",
            str(benchmark),
            "--task",
            "S07",
            "--output-dir",
            str(tmp_path / "out"),
            "--pico-command",
            f"{sys.executable} {fake_pico}",
        ],
        cwd="/Users/martinlos/code/pico",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
