import json

from pico.evaluation.trace_consistency import (
    compare_report_to_trace,
    compare_task_state_to_report,
    load_trace,
    summarize_trace,
)


def test_trace_summary_recomputes_tool_counts_stop_reason_and_artifacts(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps({"event": "tool_executed", "name": "read_file", "tool_status": "success"}),
                json.dumps(
                    {
                        "event": "tool_executed",
                        "tool_name": "run_shell",
                        "tool_status": "error",
                        "security_event_type": "sandbox_denied",
                        "full_output_artifact": "artifacts/output.txt",
                    }
                ),
                json.dumps({"event": "run_finished", "stop_reason": "final_answer_returned", "status": "completed"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_trace(load_trace(trace_path))

    assert summary["tool_steps"] == 2
    assert summary["tool_name_counts"] == {"read_file": 1, "run_shell": 1}
    assert summary["tool_status_counts"] == {"success": 1, "error": 1}
    assert summary["security_event_counts"] == {"sandbox_denied": 1}
    assert summary["stop_reason"] == "final_answer_returned"
    assert summary["status"] == "completed"
    assert summary["artifact_paths"] == ["artifacts/output.txt"]


def test_report_and_task_state_consistency_checks_are_explicit():
    trace_summary = {
        "status": "completed",
        "stop_reason": "final_answer_returned",
        "tool_steps": 2,
        "tool_name_counts": {"read_file": 1, "run_shell": 1},
        "tool_status_counts": {"success": 2},
        "security_event_counts": {},
    }
    report = {
        "status": "completed",
        "stop_reason": "final_answer_returned",
        "tool_steps": 2,
        "tool_name_counts": {"read_file": 1, "run_shell": 1},
        "tool_status_counts": {"success": 2},
        "security_event_counts": {},
    }
    task_state = {"status": "completed", "stop_reason": "final_answer_returned"}

    assert all(check.passed for check in compare_report_to_trace(report, trace_summary))
    assert all(check.passed for check in compare_task_state_to_report(task_state, report))

    broken_report = dict(report)
    broken_report["tool_steps"] = 1
    failures = compare_report_to_trace(broken_report, trace_summary)

    assert any(not check.passed and check.name == "report_tool_steps_match_trace" for check in failures)


def test_report_trace_consistency_allows_runtime_reports_without_count_maps():
    trace_summary = {
        "status": "completed",
        "stop_reason": "final_answer_returned",
        "tool_steps": 1,
        "tool_name_counts": {"run_shell": 1},
        "tool_status_counts": {"success": 1},
        "security_event_counts": {},
    }
    report = {
        "status": "completed",
        "stop_reason": "final_answer_returned",
        "tool_steps": 1,
    }

    assert all(check.passed for check in compare_report_to_trace(report, trace_summary))
