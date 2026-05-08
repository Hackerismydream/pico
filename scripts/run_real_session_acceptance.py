#!/usr/bin/env python3
"""Run deterministic real-session acceptance scenarios for Pico."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext  # noqa: E402
from pico.features.skills_runtime import invoke_skill  # noqa: E402

SUMMARY_JSON = "gate8-real-session-acceptance.json"
SUMMARY_MARKDOWN = "gate8-real-session-acceptance.md"


def run_acceptance(output_dir):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = [
        _run_scenario(output_dir, "plan_todo_explore", _scenario_plan_todo_explore),
        _run_scenario(output_dir, "skill_inline", _scenario_skill_inline),
        _run_scenario(output_dir, "worker_write_scope", _scenario_worker_write_scope),
        _run_scenario(output_dir, "security_rejection", _scenario_security_rejection),
    ]
    summary = {
        "status": "passed" if all(item["status"] == "passed" for item in scenarios) else "failed",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    (output_dir / SUMMARY_JSON).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / SUMMARY_MARKDOWN).write_text(render_markdown(summary) + "\n", encoding="utf-8")
    return summary


def render_markdown(summary):
    lines = [
        "# Gate8 Real Session Acceptance",
        "",
        f"- status: `{summary['status']}`",
        f"- scenarios: `{summary['scenario_count']}`",
        "",
        "| Scenario | Status | Report | Trace | Events |",
        "|---|---|---|---|---|",
    ]
    for scenario in summary["scenarios"]:
        lines.append(
            "| {id} | {status} | `{report}` | `{trace}` | `{events}` |".format(
                id=scenario["id"],
                status=scenario["status"],
                report=scenario.get("report_path", ""),
                trace=scenario.get("trace_path", ""),
                events=scenario.get("session_event_path", ""),
            )
        )
    return "\n".join(lines)


def _run_scenario(output_dir, scenario_id, runner):
    workspace = output_dir / "workspaces" / scenario_id
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        record = runner(output_dir, workspace)
        record["status"] = "passed" if all(check["status"] == "passed" for check in record["checks"]) else "failed"
        return record
    except Exception as exc:
        return {
            "id": scenario_id,
            "status": "failed",
            "workspace_relpath": _relpath(workspace, output_dir),
            "error": str(exc),
            "checks": [{"name": "scenario_exception", "status": "failed", "detail": str(exc)}],
        }


def _scenario_plan_todo_explore(output_dir, workspace):
    _write_readme(workspace, "Gate8 plan fixture.\n")
    agent = _build_agent(
        workspace,
        [
            '<tool>{"name":"todo_add","args":{"content":"Draft Gate8 plan","status":"in_progress","priority":"high"}}</tool>',
            '<tool>{"name":"agent","args":{"description":"Inspect fixture","prompt":"Read README.md","subagent_type":"Explore"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            "<final>Fixture inspected.</final>",
            '<tool>{"name":"todo_update","args":{"todo_id":"todo_1","status":"done","note":"plan written"}}</tool>',
            '<tool name="write_file" path=".pico/plans/gate8-plan.md"><content># Gate8 Plan\n- Evidence harness\n</content></tool>',
            "<final>Gate8 plan ready.</final>",
        ],
        max_steps=6,
    )
    agent.enter_plan_mode("gate8")
    answer = agent.ask("Plan Gate8 with todo and Explore evidence")
    return _finalize(
        output_dir,
        workspace,
        agent,
        "plan_todo_explore",
        checks=[
            _check("answer", answer == "Gate8 plan ready.", answer),
            _check("plan_file", (workspace / ".pico" / "plans" / "gate8-plan.md").is_file()),
            _check("todo_done", agent.session["todos"]["items"][0]["status"] == "done"),
            _check("explore_worker", agent.session["workers"]["items"][0]["subagent_type"] == "Explore"),
        ],
    )


def _scenario_skill_inline(output_dir, workspace):
    _write_readme(workspace, "Gate8 skill fixture.\n")
    skill_dir = workspace / ".pico" / "skills" / "evidence"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: evidence
description: Inspect evidence target
allowed-tools: read_file
---
Inspect $ARGUMENTS and report the evidence path.
""",
        encoding="utf-8",
    )
    agent = _build_agent(
        workspace,
        [
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            "<final>Skill evidence checked.</final>",
        ],
        max_steps=4,
    )
    answer = invoke_skill(agent, "evidence", "README.md")
    events = _read_events(agent)
    return _finalize(
        output_dir,
        workspace,
        agent,
        "skill_inline",
        checks=[
            _check("answer", answer == "Skill evidence checked.", answer),
            _check("skill_invoked", any(event["event"] == "skill_invoked" for event in events)),
            _check("skill_completed", any(event["event"] == "skill_completed" for event in events)),
        ],
    )


def _scenario_worker_write_scope(output_dir, workspace):
    _write_readme(workspace, "Gate8 worker fixture.\n")
    agent = _build_agent(
        workspace,
        [
            '<tool>{"name":"agent","args":{"description":"Write scoped notes","prompt":"Create first note","subagent_type":"worker","write_scope":["notes"]}}</tool>',
            '<tool name="write_file" path="notes/first.txt"><content>first\n</content></tool>',
            "<final>First note written.</final>",
            '<tool>{"name":"send_message","args":{"to":"agent_1","message":"Create second note"}}</tool>',
            '<tool name="write_file" path="notes/second.txt"><content>second\n</content></tool>',
            "<final>Second note written.</final>",
            "<final>Scoped worker completed.</final>",
        ],
        max_steps=6,
    )
    answer = agent.ask("Use a scoped worker twice")
    return _finalize(
        output_dir,
        workspace,
        agent,
        "worker_write_scope",
        checks=[
            _check("answer", answer == "Scoped worker completed.", answer),
            _check("first_note", (workspace / "notes" / "first.txt").read_text(encoding="utf-8") == "first\n"),
            _check("second_note", (workspace / "notes" / "second.txt").read_text(encoding="utf-8") == "second\n"),
            _check("write_scope", agent.session["workers"]["items"][0]["write_scope"] == ["notes"]),
        ],
    )


def _scenario_security_rejection(output_dir, workspace):
    _write_readme(workspace, "Gate8 security fixture.\n")
    agent = _build_agent(
        workspace,
        [
            '<tool>{"name":"read_file","args":{"path":"../outside.txt","start":1,"end":1}}</tool>',
            "<final>Path escape blocked.</final>",
        ],
        max_steps=3,
    )
    answer = agent.ask("Try to read outside the workspace")
    events = _read_events(agent)
    return _finalize(
        output_dir,
        workspace,
        agent,
        "security_rejection",
        checks=[
            _check("answer", answer == "Path escape blocked.", answer),
            _check("invalid_arguments", any(event.get("tool_error_code") == "invalid_arguments" for event in events)),
            _check("no_outside_file", not (output_dir / "outside.txt").exists()),
        ],
    )


def _build_agent(workspace, outputs, max_steps=6):
    workspace_context = WorkspaceContext.build(workspace)
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace_context,
        session_store=SessionStore(workspace / ".pico" / "sessions"),
        approval_policy="auto",
        max_steps=max_steps,
    )


def _finalize(output_dir, workspace, agent, scenario_id, checks):
    run_dir = agent.current_run_dir
    report_path = run_dir / "report.json"
    trace_path = run_dir / "trace.jsonl"
    task_state_path = run_dir / "task_state.json"
    session_event_path = agent.session_event_bus.path
    checks.extend(
        [
            _check("report_exists", report_path.is_file()),
            _check("trace_exists", trace_path.is_file()),
            _check("task_state_exists", task_state_path.is_file()),
            _check("session_events_exists", session_event_path.is_file()),
        ]
    )
    return {
        "id": scenario_id,
        "workspace_relpath": _relpath(workspace, output_dir),
        "session_path": _relpath(agent.session_path, output_dir),
        "session_event_path": _relpath(session_event_path, output_dir),
        "run_dir": _relpath(run_dir, output_dir),
        "report_path": _relpath(report_path, output_dir),
        "trace_path": _relpath(trace_path, output_dir),
        "task_state_path": _relpath(task_state_path, output_dir),
        "checks": checks,
    }


def _write_readme(workspace, text):
    (workspace / "README.md").write_text(text, encoding="utf-8")


def _read_events(agent):
    return [
        json.loads(line)
        for line in agent.session_event_bus.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _check(name, condition, detail=""):
    return {"name": name, "status": "passed" if condition else "failed", "detail": str(detail)}


def _relpath(path, root):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Run Pico Gate8 deterministic real-session acceptance scenarios.")
    parser.add_argument("--output-dir", default="artifacts/gate8-real-session-acceptance", help="Directory for workspaces and summary artifacts.")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    summary = run_acceptance(Path(args.output_dir))
    print(json.dumps({"status": summary["status"], "scenario_count": summary["scenario_count"]}, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
