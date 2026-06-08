import pytest

from pico.core.turn_transitions import (
    CONTINUE_TOOL_BATCH_EXECUTED,
    TERMINAL_FINAL_ANSWER_RETURNED,
    build_transition,
    reduce_transition_summary,
)


def test_build_transition_uses_string_kind_values():
    event = build_transition(
        kind="continue",
        reason=CONTINUE_TOOL_BATCH_EXECUTED,
        turn_index=2,
        attempt_index=3,
        tool_call_count=2,
        tool_requested_count=3,
        tool_executed_count=2,
    )

    assert event == {
        "kind": "continue",
        "reason": "tool_batch_executed",
        "turn_index": 2,
        "attempt_index": 3,
        "tool_call_count": 2,
        "tool_requested_count": 3,
        "tool_executed_count": 2,
    }


def test_reduce_transition_summary_allows_only_one_terminal_transition():
    summary = reduce_transition_summary(
        {},
        build_transition(
            kind="terminal",
            reason=TERMINAL_FINAL_ANSWER_RETURNED,
            turn_index=1,
            attempt_index=1,
            stop_reason=TERMINAL_FINAL_ANSWER_RETURNED,
        ),
    )

    with pytest.raises(ValueError, match="terminal transition"):
        reduce_transition_summary(
            summary,
            build_transition(
                kind="terminal",
                reason=TERMINAL_FINAL_ANSWER_RETURNED,
                turn_index=2,
                attempt_index=2,
                stop_reason=TERMINAL_FINAL_ANSWER_RETURNED,
            ),
        )


def test_reduce_transition_summary_tracks_tool_request_and_execution_counts():
    summary = reduce_transition_summary(
        {},
        build_transition(
            kind="continue",
            reason=CONTINUE_TOOL_BATCH_EXECUTED,
            turn_index=1,
            attempt_index=1,
            tool_call_count=1,
            tool_requested_count=2,
            tool_executed_count=1,
        ),
    )

    assert summary["tool_requested_count"] == 2
    assert summary["tool_executed_count"] == 1
