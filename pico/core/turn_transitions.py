"""Loop transition contracts and summary reduction."""

from enum import Enum


CONTINUE_PROVIDER_RETRY = "provider_retry"
CONTINUE_PARSE_RETRY = "parse_retry"
CONTINUE_TOOL_BATCH_EXECUTED = "tool_batch_executed"
CONTINUE_PLAN_NOTICE = "plan_notice"
CONTINUE_FINAL_READINESS_NOTICE = "final_readiness_notice"
TERMINAL_FINAL_ANSWER_RETURNED = "final_answer_returned"
TERMINAL_ABORTED = "aborted"
TERMINAL_MODEL_ERROR = "model_error"
TERMINAL_STEP_LIMIT_REACHED = "step_limit_reached"
TERMINAL_RETRY_LIMIT_REACHED = "retry_limit_reached"
TERMINAL_FINAL_GATE_BLOCKED = "final_gate_blocked"


class TransitionKind(str, Enum):
    CONTINUE = "continue"
    TERMINAL = "terminal"


def build_transition(
    *,
    kind,
    reason,
    turn_index,
    attempt_index,
    tool_call_count=0,
    stop_reason="",
):
    payload = {
        "kind": TransitionKind(kind).value,
        "reason": str(reason),
        "turn_index": int(turn_index),
        "attempt_index": int(attempt_index),
    }
    if tool_call_count:
        payload["tool_call_count"] = int(tool_call_count)
    if stop_reason:
        payload["stop_reason"] = str(stop_reason)
    return payload


def reduce_transition_summary(summary, transition):
    summary = dict(summary or {})
    kind = str(transition.get("kind", ""))
    reason = str(transition.get("reason", ""))
    reasons = dict(summary.get("reasons", {}) or {})
    reasons[reason] = reasons.get(reason, 0) + 1
    summary["reasons"] = reasons
    summary["max_attempt_index"] = max(
        int(summary.get("max_attempt_index", 0) or 0),
        int(transition.get("attempt_index", 0) or 0),
    )
    if kind == TransitionKind.CONTINUE.value:
        summary["continue_count"] = int(summary.get("continue_count", 0) or 0) + 1
        summary.setdefault("terminal_count", 0)
        return summary
    if kind == TransitionKind.TERMINAL.value:
        if int(summary.get("terminal_count", 0) or 0) >= 1:
            raise ValueError("run already has a terminal transition")
        summary["terminal_count"] = 1
        summary.setdefault("continue_count", 0)
        summary["terminal_reason"] = str(
            transition.get("stop_reason") or transition.get("reason") or ""
        )
        return summary
    return summary


def emit_transition(
    agent, task_state, *, kind, reason, tool_call_count=0, stop_reason=""
):
    payload = build_transition(
        kind=kind,
        reason=reason,
        turn_index=task_state.attempts,
        attempt_index=task_state.attempts,
        tool_call_count=tool_call_count,
        stop_reason=stop_reason,
    )
    return agent.emit_trace(task_state, "loop_transition", payload)
