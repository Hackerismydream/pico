"""Token pressure measurement and tier classification."""

from dataclasses import dataclass


TIER_THRESHOLDS = (0.60, 0.80, 0.95)
TIER_NAMES = ("tier0_observe", "tier1_snip", "tier2_prune", "tier3_summary")


@dataclass(frozen=True)
class ContextPressure:
    ratio: float
    tier: str
    source: str


def measure_pressure(prompt_chars: int, total_budget: int) -> ContextPressure:
    ratio = int(prompt_chars) / max(1, int(total_budget))
    if ratio < 0.60:
        tier = "tier0_observe"
    elif ratio < 0.80:
        tier = "tier1_snip"
    elif ratio < 0.95:
        tier = "tier2_prune"
    else:
        tier = "tier3_summary"
    return ContextPressure(ratio=round(ratio, 4), tier=tier, source="char_estimate")
