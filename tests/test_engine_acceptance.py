import json
import shlex
import sys

from pico.testing import ScriptedModelClient
from pico import Pico, SessionStore, WorkspaceContext
from pico.core.task_state import TaskState
from pico.core.turn_transitions import emit_transition
from pico.providers import ProviderError


def build_agent(tmp_path, outputs, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=ScriptedModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_engine_streams_a_real_session_with_tool_artifacts(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/result.txt"><content>ok\n</content></tool>',
            "<final>Wrote it.</final>",
        ],
    )

    events = list(agent.engine.run_turn("create the result file"))

    assert [event["type"] for event in events] == [
        "turn_started",
        "model_requested",
        "model_parsed",
        "tool_call",
        "tool_result",
        "model_requested",
        "model_parsed",
        "final",
        "turn_finished",
    ]
    assert events[-2]["content"] == "Wrote it."
    assert (tmp_path / "notes" / "result.txt").read_text(encoding="utf-8") == "ok\n"

    persisted_events = read_jsonl(agent.session_event_bus.path)
    assert [event["event"] for event in persisted_events][-6:] == [
        "tool_finished",
        "context_usage_recorded",
        "model_requested",
        "model_parsed",
        "assistant_message",
        "turn_finished",
    ]

    report_path = agent.current_run_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["final_answer"] == "Wrote it."


def test_engine_records_loop_transitions_without_changing_stream(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/result.txt"><content>ok\n</content></tool>',
            "<final>Wrote it.</final>",
        ],
    )

    events = list(agent.engine.run_turn("create the result file"))

    assert [event["type"] for event in events] == [
        "turn_started",
        "model_requested",
        "model_parsed",
        "tool_call",
        "tool_result",
        "model_requested",
        "model_parsed",
        "final",
        "turn_finished",
    ]
    trace_events = read_jsonl(agent.current_run_dir / "trace.jsonl")
    transitions = [event for event in trace_events if event["event"] == "loop_transition"]
    assert [event["reason"] for event in transitions] == [
        "tool_batch_executed",
        "final_answer_returned",
    ]

    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["evidence_summaries"]["transition_summary"] == {
        "continue_count": 1,
        "terminal_count": 1,
        "terminal_reason": "final_answer_returned",
        "reasons": {
            "tool_batch_executed": 1,
            "final_answer_returned": 1,
        },
        "max_attempt_index": 2,
        "tool_requested_count": 1,
        "tool_executed_count": 1,
    }


def test_engine_reports_context_budget_summary_from_prompt_metadata(tmp_path):
    agent = build_agent(tmp_path, ["<final>Done.</final>"])

    list(agent.engine.run_turn("summarize context usage"))

    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    summary = report["evidence_summaries"]["context_budget_summary"]
    usage = report["prompt_metadata"]["context_usage"]
    assert summary["estimated_tokens"] == usage["total_estimated_tokens"]
    assert summary["effective_window"] == (
        usage["context_window"] - usage["reserved_output_tokens"]
    )
    assert summary["prompt_changed_by_phase_3"] is False
    assert summary["reductions"] == []


def test_runtime_consumer_errors_are_visible_in_task_state(tmp_path):
    agent = build_agent(tmp_path, [])
    task_state = TaskState.create(
        task_id=agent.new_task_id(),
        run_id=agent.new_run_id(),
        user_request="exercise consumer errors",
    )
    agent.current_run_dir = agent.run_store.start_run(task_state)

    emit_transition(
        agent,
        task_state,
        kind="terminal",
        reason="final_answer_returned",
        stop_reason="final_answer_returned",
    )
    emit_transition(
        agent,
        task_state,
        kind="terminal",
        reason="retry_limit_reached",
        stop_reason="retry_limit_reached",
    )

    errors = task_state.evidence_summaries["consumer_errors"]
    assert errors[-1]["consumer"] == "EvidenceSummaryConsumer"
    assert errors[-1]["event"] == "loop_transition"
    assert "terminal transition" in errors[-1]["message"]


def test_engine_records_provider_error_as_failed_run(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            ProviderError(
                "rate limited",
                provider="openai",
                model="gpt-test",
                base_url="https://example.test/v1",
                code="rate_limited",
                http_status=429,
                retryable=True,
                attempts=3,
                retry_count=2,
            )
        ],
    )

    events = list(agent.engine.run_turn("call a rate limited provider"))

    assert events[-2]["type"] == "stop"
    assert "rate_limited" in events[-2]["content"]
    assert events[-2]["content"].startswith("模型错误")
    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "failed"
    assert report["stop_reason"] == "model_error"
    assert report["prompt_metadata"]["provider_error"]["code"] == "rate_limited"
    assert report["prompt_metadata"]["provider_error"]["retry_count"] == 2

    trace_events = read_jsonl(agent.current_run_dir / "trace.jsonl")
    model_error = next(
        event for event in trace_events if event["event"] == "model_error"
    )
    assert model_error["error"]["http_status"] == 429

    persisted_events = read_jsonl(agent.session_event_bus.path)
    assert any(
        event["event"] == "model_error" and event["code"] == "rate_limited"
        for event in persisted_events
    )


def test_engine_executes_multiple_tool_calls_from_one_model_response(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            "\n".join(
                [
                    '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                    '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
                ]
            ),
            "<final>Both tools ran.</final>",
        ],
    )

    events = list(agent.engine.run_turn("inspect the workspace"))

    assert [event["type"] for event in events if event["type"] == "tool_call"] == [
        "tool_call",
        "tool_call",
    ]
    tool_history = [item for item in agent.session["history"] if item["role"] == "tool"]
    assert [item["name"] for item in tool_history] == ["read_file", "list_files"]
    assert events[-2]["content"] == "Both tools ran."
    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    transition = next(
        event
        for event in trace
        if event["event"] == "loop_transition" and event["reason"] == "tool_batch_executed"
    )
    assert transition["tool_requested_count"] == 2
    assert transition["tool_executed_count"] == 2


def test_multi_tool_transition_distinguishes_requested_and_executed_counts(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            "\n".join(
                [
                    '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                    '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
                ]
            ),
            "<final>not reached</final>",
        ],
        max_steps=1,
    )

    events = list(agent.engine.run_turn("inspect with too many tools"))

    assert [event["type"] for event in events if event["type"] == "tool_call"] == [
        "tool_call"
    ]
    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    transition = next(
        event
        for event in trace
        if event["event"] == "loop_transition" and event["reason"] == "tool_batch_executed"
    )
    assert transition["tool_requested_count"] == 2
    assert transition["tool_executed_count"] == 1


def test_empty_response_provider_error_is_retried_once_before_failing(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            ProviderError(
                "empty provider response",
                provider="anthropic",
                model="deepseek-v4-pro",
                base_url="https://api.deepseek.com/anthropic/v1",
                code="empty_response",
                retryable=False,
            ),
            "<final>Recovered.</final>",
        ],
    )

    events = list(agent.engine.run_turn("recover from provider empty response"))

    assert events[-2]["content"] == "Recovered."
    persisted_events = read_jsonl(agent.session_event_bus.path)
    assert any(
        event["event"] == "model_retry_scheduled" and event["code"] == "empty_response"
        for event in persisted_events
    )
    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    transitions = [event for event in trace if event["event"] == "loop_transition"]
    assert [event["reason"] for event in transitions] == [
        "provider_retry",
        "final_answer_returned",
    ]
    assert [event["type"] for event in events] == [
        "turn_started",
        "model_requested",
        "model_requested",
        "model_parsed",
        "final",
        "turn_finished",
    ]


def test_parse_retry_transition_preserves_stream_order(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            "malformed response",
            "<final>Recovered.</final>",
        ],
    )

    events = list(agent.engine.run_turn("recover from parse retry"))

    assert [event["type"] for event in events] == [
        "turn_started",
        "model_requested",
        "model_parsed",
        "retry",
        "model_requested",
        "model_parsed",
        "final",
        "turn_finished",
    ]
    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    transitions = [event for event in trace if event["event"] == "loop_transition"]
    assert [event["reason"] for event in transitions] == [
        "parse_retry",
        "final_answer_returned",
    ]


def test_retry_limit_transition_is_terminal(tmp_path):
    agent = build_agent(
        tmp_path,
        ["malformed 1", "malformed 2", "malformed 3"],
        max_steps=1,
    )

    events = list(agent.engine.run_turn("hit retry limit"))

    assert events[-1]["stop_reason"] == "retry_limit_reached"
    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    transitions = [event for event in trace if event["event"] == "loop_transition"]
    assert [event["reason"] for event in transitions] == [
        "parse_retry",
        "parse_retry",
        "parse_retry",
        "retry_limit_reached",
    ]
    assert transitions[-1]["kind"] == "terminal"


def test_worker_notification_drained_during_turn_is_streamed(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"agent","args":{"description":"Inspect","prompt":"Read README","subagent_type":"Explore"}}</tool>',
            "<final>Child done.</final>",
            "<final>Parent done.</final>",
        ],
        max_steps=3,
    )

    events = list(agent.engine.run_turn("delegate and continue"))

    notifications = [
        event for event in events if event["type"] == "worker_notification"
    ]
    assert len(notifications) == 1
    assert "<task-id>agent_1</task-id>" in notifications[0]["content"]


def test_plan_notice_transition_preserves_runtime_notice_stream_order(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            "<final>Looks done.</final>",
            '<tool name="write_file" path=".pico/plans/v3-plan.md"><content># Plan\n</content></tool>',
            "<final>Now done.</final>",
        ],
        max_steps=3,
    )
    agent.enter_plan_mode("v3")

    events = list(agent.engine.run_turn("make a plan"))

    assert [event["type"] for event in events] == [
        "turn_started",
        "model_requested",
        "model_parsed",
        "runtime_notice",
        "model_requested",
        "model_parsed",
        "tool_call",
        "tool_result",
        "model_requested",
        "model_parsed",
        "final",
        "turn_finished",
    ]
    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    transitions = [event for event in trace if event["event"] == "loop_transition"]
    assert [event["reason"] for event in transitions] == [
        "plan_notice",
        "tool_batch_executed",
        "final_answer_returned",
    ]


def test_step_limit_triggers_graceful_summary_when_model_complies(tmp_path):
    """达到 step_limit 时，runtime 让模型用剩余预算给一个 <final> 总结，
    用户看到的就不再是冷冰冰的 'Stopped after reaching the step limit'。"""
    agent = build_agent(
        tmp_path,
        [
            # 1 步用掉 max_steps=1，触发 step_limit
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            # step_limit 总结调用——模型遵守了 notice 给 final
            "<final>已经列出文件。还差读取具体内容。继续请用 /resume。</final>",
        ],
        max_steps=1,
    )

    events = list(agent.engine.run_turn("trigger step limit"))

    stop_event = next(e for e in events if e["type"] == "stop")
    assert "已经列出文件" in stop_event["content"]
    assert "step 预算上限" in stop_event["content"]
    # 不能是历史的冷消息
    assert "Stopped after reaching the step limit" not in stop_event["content"]


def test_step_limit_falls_back_to_cold_message_when_summary_fails(tmp_path):
    """模型如果连总结都返回 retry，不能死循环，要 fall back 到老消息。"""
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            # step_limit 总结时模型乱说话（没 <tool> 也没 <final>），解析为 retry
            "I cannot comply.",
        ],
        max_steps=1,
    )

    events = list(agent.engine.run_turn("trigger step limit"))

    stop_event = next(e for e in events if e["type"] == "stop")
    assert "Stopped after reaching the step limit" in stop_event["content"]


def test_soft_final_readiness_reminds_once_then_allows_unchanged_final(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/result.txt"><content>ok\n</content></tool>',
            "<final>Done without verification.</final>",
            "<final>Done without verification.</final>",
        ],
        final_readiness_mode="soft",
        max_steps=3,
    )

    events = list(agent.engine.run_turn("write the result"))

    assert [event["type"] for event in events if event["type"] == "runtime_notice"] == [
        "runtime_notice"
    ]
    assert events[-2]["type"] == "final"
    assert events[-2]["content"] == "Done without verification."

    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    readiness = [event for event in trace if event["event"] == "final_readiness_decision"]
    assert [(event["decision"], event["reminder_already_sent"]) for event in readiness] == [
        ("remind", False),
        ("warn", True),
    ]
    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["evidence_summaries"]["final_readiness_summary"]["remind_count"] == 1
    assert report["evidence_summaries"]["final_readiness_summary"]["warn_count"] == 1


def test_strict_final_readiness_blocks_unverified_workspace_changes(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/result.txt"><content>ok\n</content></tool>',
            "<final>Done without verification.</final>",
        ],
        final_readiness_mode="strict",
        max_steps=2,
    )

    events = list(agent.engine.run_turn("write the result"))

    stop_event = next(event for event in events if event["type"] == "stop")
    assert "changed_paths_without_verification" in stop_event["content"]
    assert events[-1]["stop_reason"] == "final_gate_blocked"

    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    readiness = [event for event in trace if event["event"] == "final_readiness_decision"]
    assert [(event["decision"], event["action"]) for event in readiness] == [
        ("block", "block")
    ]

    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "stopped"
    assert report["stop_reason"] == "final_gate_blocked"
    assert report["evidence_summaries"]["final_readiness_summary"]["block_count"] == 1


def test_strict_final_readiness_blocks_partial_success_workspace_changes(tmp_path):
    command = (
        f"{shlex.quote(sys.executable)} -c "
        + shlex.quote(
            "from pathlib import Path; Path('notes/result.txt').parent.mkdir(exist_ok=True); "
            "Path('notes/result.txt').write_text('partial\\n'); raise SystemExit(1)"
        )
    )
    agent = build_agent(
        tmp_path,
        [
            f'<tool>{{"name":"run_shell","args":{{"command":{json.dumps(command)},"timeout":20}}}}</tool>',
            "<final>Partial write is fine.</final>",
        ],
        final_readiness_mode="strict",
        max_steps=2,
    )

    events = list(agent.engine.run_turn("write the result with shell"))

    stop_event = next(event for event in events if event["type"] == "stop")
    assert "partial_success_workspace_changed" in stop_event["content"]
    assert events[-1]["stop_reason"] == "final_gate_blocked"

    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    tool_event = next(event for event in trace if event["event"] == "tool_executed")
    assert tool_event["status"] == "partial_success"
    assert tool_event["workspace_changed"] is True

    readiness = [event for event in trace if event["event"] == "final_readiness_decision"]
    assert [(event["decision"], event["action"]) for event in readiness] == [
        ("block", "block")
    ]


def test_verification_signal_passes_after_workspace_verification(tmp_path):
    command = f"{shlex.quote(sys.executable)} -m compileall notes"
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/result.py"><content>VALUE = 1\n</content></tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":{json.dumps(command)},"timeout":20}}}}</tool>',
            "<final>Verified.</final>",
        ],
        max_steps=3,
    )

    events = list(agent.engine.run_turn("write and verify python code"))

    assert events[-2]["content"] == "Verified."
    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    signal = report["evidence_summaries"]["verification_signal"]
    assert signal["state"] == "passed"
    assert signal["command"] == command
    assert signal["command_class"] == "compile"
    assert signal["after_last_workspace_change"] is True
    assert signal["changed_paths_present"] is True
    assert signal["covers_changed_paths"] is False
    assert signal["coverage_confidence"] == "unknown"
    assert "notes/result.py" in signal["changed_paths"]
