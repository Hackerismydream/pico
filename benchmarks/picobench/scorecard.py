from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class DimensionScore:
    earned: float
    maximum: float


@dataclass(frozen=True)
class ScorecardResult:
    schema: str
    diagnostic_score: float
    certified_score: float | None
    dimensions: dict[str, DimensionScore]
    certification_gates: dict[str, bool]
    evidence: dict[str, bool]


def compute_scorecard(
    formal_summary: Mapping[str, Any],
    runtime_evidence: Mapping[str, Any],
    *,
    memory_treatment_pass_rate: float | None = None,
    memory_safety_current: bool = False,
    tokenwise_current_evidence: bool = False,
    tokenwise_current_claim_eligible: bool = False,
    turn_efficiency_current_evidence: bool = False,
    turn_efficiency_current_claim_eligible: bool = False,
    scoring_spec_preregistered: bool = False,
) -> ScorecardResult:
    metrics = _mapping(formal_summary.get("metrics"), "formal metrics")
    context_rate = _pass_rate(
        metrics,
        numerator="context.treatment_pass_count",
        denominator="context.expected_pair_count",
    )
    tool_rate = _pass_rate(
        metrics,
        numerator="tool_mcp.treatment_pass_count",
        denominator="tool_mcp.expected_pair_count",
        fallback_denominator="tool_mcp.pair_measurement_count",
    )
    memory_available = memory_treatment_pass_rate is not None
    memory_rate = _rate(memory_treatment_pass_rate or 0.0)
    capability = 50.0 * (context_rate + tool_rate + memory_rate) / 3.0

    runtime_current = runtime_evidence.get("claim_eligible") is True
    reliability = 20.0 if runtime_current else 0.0

    context_efficiency = metrics.get("context.positive_claim_eligible") is True
    tool_efficiency = metrics.get("tool_mcp.positive_claim_eligible") is True
    efficiency_lanes = (
        tokenwise_current_claim_eligible,
        context_efficiency,
        tool_efficiency,
        turn_efficiency_current_claim_eligible,
    )
    efficiency = 5.0 * sum(bool(value) for value in efficiency_lanes)

    process_gates = (
        metrics.get("tool_mcp.all_initial_visible_sets_differ") is True,
        metrics.get("tool_mcp.all_mcp_arms_connected") is True,
        metrics.get("tool_mcp.invalid_target_call_rate_noninferior") is True,
        metrics.get("tool_mcp.exact_target_repeat_rate_noninferior") is True,
    )
    process = 10.0 * sum(process_gates) / len(process_gates)

    dimensions = {
        "capability": DimensionScore(round(capability, 4), 50.0),
        "reliability": DimensionScore(round(reliability, 4), 20.0),
        "efficiency": DimensionScore(round(efficiency, 4), 20.0),
        "process": DimensionScore(round(process, 4), 10.0),
    }
    diagnostic = round(sum(value.earned for value in dimensions.values()), 4)
    evidence = {
        "context_current": True,
        "tool_mcp_current": True,
        "memory_current": memory_available,
        "runtime_current": runtime_current,
        "tokenwise_current": tokenwise_current_evidence,
        "turn_efficiency_current": turn_efficiency_current_evidence,
    }
    certification_gates = {
        "scoring_spec_preregistered": scoring_spec_preregistered,
        "ship_complete": formal_summary.get("ship_complete") is True,
        "measurement_valid": formal_summary.get("measurement_valid") is True,
        "evidence_complete": all(evidence.values()),
        "safety_evidence_complete": memory_safety_current,
    }
    certified = diagnostic if all(certification_gates.values()) else None
    return ScorecardResult(
        schema="pico.picobench.multidimensional-score.v0",
        diagnostic_score=diagnostic,
        certified_score=certified,
        dimensions=dimensions,
        certification_gates=certification_gates,
        evidence=evidence,
    )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _pass_rate(
    metrics: Mapping[str, Any],
    *,
    numerator: str,
    denominator: str,
    fallback_denominator: str | None = None,
) -> float:
    raw_denominator = metrics.get(denominator)
    if raw_denominator is None and fallback_denominator is not None:
        raw_denominator = metrics.get(fallback_denominator)
    if not isinstance(raw_denominator, (int, float)) or raw_denominator <= 0:
        raise ValueError(f"{denominator} must be positive")
    raw_numerator = metrics.get(numerator)
    if not isinstance(raw_numerator, (int, float)):
        raise ValueError(f"{numerator} must be numeric")
    return _rate(float(raw_numerator) / float(raw_denominator))


def _rate(value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError("rates must be between zero and one")
    return value


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, str(path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute the PicoBench multidimensional diagnostic score.",
    )
    parser.add_argument("--formal-summary", required=True, type=Path)
    parser.add_argument("--runtime-evidence", required=True, type=Path)
    args = parser.parse_args()
    result = compute_scorecard(
        _read_json(args.formal_summary),
        _read_json(args.runtime_evidence),
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
