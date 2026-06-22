"""Context-pressure checks for final-readiness decisions."""

CONTEXT_HARD_PRESSURE_RATIO = 0.95


def context_pressure_without_reduction(context):
    try:
        pressure = float(context.get("pressure_ratio", 0) or 0)
    except (TypeError, ValueError):
        pressure = 0.0
    reductions = context.get("reductions", []) or []
    return pressure >= CONTEXT_HARD_PRESSURE_RATIO and not any(
        int(item.get("saved_chars", 0) or 0) > 0 for item in reductions
    )


def tier3_summary_without_delta(context):
    return (
        str(context.get("pressure_tier", "")) == "tier3_summary"
        and bool(context.get("summary_called", False))
        and int(context.get("summary_delta_event_count", 0) or 0) == 0
    )


def replacement_ledger_disabled_under_pressure(context):
    return str(context.get("pressure_tier", "")) in {
        "tier2_prune",
        "tier3_summary",
    } and context.get("replacement_ledger_enabled") is False


def provider_usage_unavailable(context):
    if not context:
        return False
    high_pressure = str(context.get("pressure_tier", "")) in {
        "tier2_prune",
        "tier3_summary",
    }
    try:
        pressure_ratio = float(context.get("pressure_ratio", 0) or 0)
    except (TypeError, ValueError):
        pressure_ratio = 0.0
    return bool(context.get("provider_usage_available") is False) and (
        high_pressure or pressure_ratio >= 0.8
    )
