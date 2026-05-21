import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
        cwd=ROOT,
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
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr


def test_pty_driver_runs_fake_cli_under_real_tty(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("fixture\n", encoding="utf-8")
    fake_pico = tmp_path / "fake_pty.py"
    fake_pico.write_text(
        """
import json
import os
import pathlib
import sys

args = sys.argv[1:]
workspace = pathlib.Path(args[args.index("--cwd") + 1])
workspace.joinpath("isatty.txt").write_text(str(os.isatty(0)), encoding="utf-8")
sys.stdin.readline()
sys.stdin.readline()
run_dir = workspace / ".pico" / "runs" / "run_1"
session_dir = workspace / ".pico" / "sessions"
run_dir.mkdir(parents=True, exist_ok=True)
session_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "report.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "tool_steps": 0}), encoding="utf-8")
(run_dir / "task_state.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "changed_paths": ["isatty.txt"]}), encoding="utf-8")
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
                        "task_id": "pty_smoke",
                        "suite": "picobench-agentic",
                        "category": "cli_behavior",
                        "repo": {"fixture": "fixture"},
                        "prompt": {"text": "/help"},
                        "execution": {"driver": "pty", "max_steps": 3, "timeout_sec": 30},
                        "tests": {"public": ["python -c \"import pathlib; assert pathlib.Path('isatty.txt').read_text() == 'True'\""]},
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
            "pty_smoke",
            "--output-dir",
            str(tmp_path / "out"),
            "--pico-command",
            f"{sys.executable} {fake_pico}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr


def test_hidden_tests_are_injected_only_after_pico_execution(tmp_path):
    visible = tmp_path / "visible"
    visible.mkdir()
    (visible / "README.md").write_text("fixture\n", encoding="utf-8")
    hidden = tmp_path / "hidden" / "hidden_tests"
    hidden.mkdir(parents=True)
    (hidden / "test_hidden.py").write_text("def test_hidden():\n    assert True\n", encoding="utf-8")
    fake_pico = tmp_path / "fake_hidden.py"
    fake_pico.write_text(
        """
import json
import pathlib
import sys

args = sys.argv[1:]
workspace = pathlib.Path(args[args.index("--cwd") + 1])
(workspace / "hidden_visible_during_run.txt").write_text(str((workspace / "hidden_tests").exists()), encoding="utf-8")
run_dir = workspace / ".pico" / "runs" / "run_1"
session_dir = workspace / ".pico" / "sessions"
run_dir.mkdir(parents=True, exist_ok=True)
session_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "report.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "tool_steps": 0}), encoding="utf-8")
(run_dir / "task_state.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "changed_paths": ["hidden_visible_during_run.txt"]}), encoding="utf-8")
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
                "suite": "picobench-core",
                "tasks": [
                    {
                        "task_id": "core_hidden",
                        "suite": "picobench-core",
                        "category": "bugfix",
                        "repo": {"fixture": "visible", "hidden_fixture": "hidden"},
                        "prompt": {"text": "Do not see hidden tests."},
                        "execution": {"driver": "one_shot_cli", "max_steps": 3, "timeout_sec": 30},
                        "tests": {
                            "public": ["python -c \"import pathlib; assert pathlib.Path('hidden_visible_during_run.txt').read_text() == 'False'\""],
                            "hidden": ["python -m pytest hidden_tests -q"],
                        },
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
            "core",
            "--benchmark",
            str(benchmark),
            "--task",
            "core_hidden",
            "--output-dir",
            str(tmp_path / "out"),
            "--pico-command",
            f"{sys.executable} {fake_pico}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    workspace = tmp_path / "out" / "workspaces" / "core_hidden-run1"
    assert (workspace / "hidden_visible_during_run.txt").read_text(encoding="utf-8") == "False"
    assert (workspace / "hidden_tests" / "test_hidden.py").exists()


def test_timeout_is_recorded_as_task_failure_not_suite_crash(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("fixture\n", encoding="utf-8")
    sleeper = tmp_path / "sleep.py"
    sleeper.write_text("import time; time.sleep(2)\n", encoding="utf-8")
    benchmark = tmp_path / "benchmark.yaml"
    benchmark.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite": "picobench-core",
                "tasks": [
                    {
                        "task_id": "timeout_task",
                        "suite": "picobench-core",
                        "category": "bugfix",
                        "repo": {"fixture": "fixture"},
                        "prompt": {"text": "timeout"},
                        "execution": {"driver": "one_shot_cli", "max_steps": 3, "timeout_sec": 1},
                        "tests": {"public": ["python -c \"assert True\""]},
                        "verifiers": [],
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
            "core",
            "--benchmark",
            str(benchmark),
            "--task",
            "timeout_task",
            "--output-dir",
            str(tmp_path / "out"),
            "--pico-command",
            f"{sys.executable} {sleeper}",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["failure_category_counts"] == {"timeout": 1}


def test_tui_driver_is_skipped_in_non_interactive_runner_instead_of_repl_fallback(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("fixture\n", encoding="utf-8")
    fake = tmp_path / "fake.py"
    fake.write_text("raise SystemExit('should not be called for tui skip')\n", encoding="utf-8")
    benchmark = tmp_path / "benchmark.yaml"
    benchmark.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite": "picobench-agentic",
                "tasks": [
                    {
                        "task_id": "R05",
                        "suite": "picobench-agentic",
                        "category": "tui",
                        "repo": {"fixture": "fixture"},
                        "prompt": {"text": "approval"},
                        "execution": {"driver": "tui", "max_steps": 3, "timeout_sec": 30},
                        "tests": {"public": ["python -c \"assert True\""]},
                        "verifiers": [],
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
            "R05",
            "--output-dir",
            str(tmp_path / "out"),
            "--pico-command",
            f"{sys.executable} {fake}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["skipped"] == 1
    assert summary["strict_passed"] == 0


def test_cli_overrides_driver_max_steps_timeout_and_can_remove_workspace(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "README.md").write_text("fixture\n", encoding="utf-8")
    fake = tmp_path / "fake.py"
    fake.write_text(
        """
import json
import pathlib
import sys

args = sys.argv[1:]
workspace = pathlib.Path(args[args.index("--cwd") + 1])
(workspace / "args.json").write_text(json.dumps(args), encoding="utf-8")
run_dir = workspace / ".pico" / "runs" / "run_1"
session_dir = workspace / ".pico" / "sessions"
run_dir.mkdir(parents=True, exist_ok=True)
session_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "report.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "tool_steps": 0}), encoding="utf-8")
(run_dir / "task_state.json").write_text(json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "changed_paths": ["args.json"]}), encoding="utf-8")
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
                "suite": "picobench-core",
                "tasks": [
                    {
                        "task_id": "override_task",
                        "suite": "picobench-core",
                        "category": "bugfix",
                        "repo": {"fixture": "fixture"},
                        "prompt": {"text": "/help"},
                        "execution": {"driver": "one_shot_cli", "max_steps": 3, "timeout_sec": 30},
                        "tests": {"public": ["python -c \"import json, pathlib; args=json.loads(pathlib.Path('args.json').read_text()); assert '--repl' in args and '--max-steps' in args and args[args.index('--max-steps') + 1] == '9'\""]},
                        "verifiers": [{"type": "evidence"}],
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
            "override_task",
            "--output-dir",
            str(output_dir),
            "--pico-command",
            f"{sys.executable} {fake}",
            "--driver",
            "repl",
            "--max-steps",
            "9",
            "--timeout-sec",
            "5",
            "--discard-workspaces",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (output_dir / "workspaces" / "override_task-run1").exists()
    assert (output_dir / "evidence" / "override_task-run1" / "report.json").exists()
