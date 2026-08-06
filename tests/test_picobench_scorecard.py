from __future__ import annotations

import pytest

from benchmarks.picobench.scorecard import compute_scorecard


def _formal_summary() -> dict[str, object]:
    return {
        "ship_complete": True,
        "measurement_valid": True,
        "metrics": {
            "context.expected_pair_count": 24,
            "context.treatment_pass_count": 0,
            "context.positive_claim_eligible": False,
            "tool_mcp.pair_measurement_count": 24,
            "tool_mcp.treatment_pass_count": 22,
            "tool_mcp.positive_claim_eligible": False,
            "tool_mcp.all_initial_visible_sets_differ": True,
            "tool_mcp.all_mcp_arms_connected": True,
            "tool_mcp.invalid_target_call_rate_noninferior": True,
            "tool_mcp.exact_target_repeat_rate_noninferior": True,
        },
    }


def test_scorecard_reports_current_diagnostic_without_certifying_it() -> None:
    result = compute_scorecard(
        _formal_summary(),
        {"claim_eligible": True},
    )

    assert result.diagnostic_score == pytest.approx(45.2778)
    assert result.certified_score is None
    assert result.dimensions["capability"].earned == pytest.approx(15.2778)
    assert result.dimensions["reliability"].earned == 20
    assert result.dimensions["efficiency"].earned == 0
    assert result.dimensions["process"].earned == 10
    assert result.certification_gates["evidence_complete"] is False


def test_scorecard_certifies_only_complete_preregistered_evidence() -> None:
    summary = _formal_summary()
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    metrics["context.positive_claim_eligible"] = True
    metrics["tool_mcp.positive_claim_eligible"] = True

    result = compute_scorecard(
        summary,
        {"claim_eligible": True},
        memory_treatment_pass_rate=0.75,
        memory_safety_current=True,
        tokenwise_current_evidence=True,
        tokenwise_current_claim_eligible=True,
        turn_efficiency_current_evidence=True,
        turn_efficiency_current_claim_eligible=True,
        scoring_spec_preregistered=True,
    )

    assert result.diagnostic_score == pytest.approx(77.7778)
    assert result.certified_score == result.diagnostic_score


def test_scorecard_rejects_invalid_rates() -> None:
    summary = _formal_summary()
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    metrics["tool_mcp.treatment_pass_count"] = 25

    with pytest.raises(ValueError, match="rates must be between"):
        compute_scorecard(summary, {"claim_eligible": True})
