"""Token pressure measurement and tier classification."""

from dataclasses import dataclass


PRESSURE_TIERS = (
    (0.60, "tier0_observe"),
    (0.80, "tier1_snip"),
    (0.95, "tier2_prune"),
)


@dataclass(frozen=True)
class ContextPressure:
    ratio: float
    tier: str
    source: str


def measure_pressure(prompt_chars: int, total_budget: int) -> ContextPressure:
    ratio = int(prompt_chars) / max(1, int(total_budget))
    tier = next((name for threshold, name in PRESSURE_TIERS if ratio < threshold), "tier3_summary")
    return ContextPressure(ratio=round(ratio, 4), tier=tier, source="char_estimate")
