"""Reduce raw trace events into compact task-state summaries."""

from .final_readiness import reduce_final_readiness_summary
from .governance import reduce_governance_summary
from .turn_transitions import reduce_transition_summary
from .verification import reduce_verification_signal


def update_evidence_summaries(summaries, event, changed_paths=None):
    summaries = dict(summaries or {})
    if event.get("event") == "loop_transition":
        summaries["transition_summary"] = reduce_transition_summary(
            summaries.get("transition_summary", {}), event
        )
    elif event.get("event") == "prompt_built":
        summaries["context_budget_summary"] = context_budget_summary(
            event.get("prompt_metadata", {})
        )
    elif event.get("event") == "governance_decision":
        summaries["governance_summary"] = reduce_governance_summary(
            summaries.get("governance_summary", {}), event
        )
    elif event.get("event") == "tool_executed":
        summaries["verification_signal"] = reduce_verification_signal(
            summaries.get("verification_signal", {}), event, changed_paths or []
        )
    elif event.get("event") == "final_readiness_decision":
        summaries["final_readiness_summary"] = reduce_final_readiness_summary(
            summaries.get("final_readiness_summary", {}), event
        )
    return summaries


def context_budget_summary(metadata):
    usage = dict(metadata.get("context_usage", {}) or {})
    window = int(usage.get("context_window", 0) or 0)
    reserved = int(usage.get("reserved_output_tokens", 0) or 0)
    effective_window = max(0, window - reserved)
    estimated_tokens = int(usage.get("total_estimated_tokens", 0) or 0)
    return {
        "estimated_tokens": estimated_tokens,
        "effective_window": effective_window,
        "reserved_output_tokens": reserved,
        "pressure_ratio": (
            round(estimated_tokens / effective_window, 4)
            if effective_window
            else 0
        ),
        "reductions": [
            *[_section_reduction(item) for item in metadata.get("budget_reductions", []) or []],
            *_microcompact_reductions(metadata),
        ],
        "prompt_changed_by_phase_3": False,
    }


def _section_reduction(item):
    before = int(item.get("before_chars", 0) or 0)
    after = int(item.get("after_chars", 0) or 0)
    return {
        "source": "section_reduction",
        "section": str(item.get("section", "")),
        "saved_chars": max(0, before - after),
    }


def _microcompact_reductions(metadata):
    history = dict(metadata.get("history", {}) or {})
    saved = int(history.get("microcompact_saved_chars", 0) or 0)
    refs = list(history.get("microcompact_artifact_refs", []) or [])
    if not saved and not refs:
        return []
    return [
        {
            "source": "microcompact",
            "section": "history",
            "saved_chars": saved,
            "artifact_refs": refs,
        }
    ]
