"""Final-readiness reason catalog.

Reason codes live here so user-facing messages, severities, and tests stay in
one place. The catalog is intentionally data-only; gate behavior belongs in
final_readiness.py.
"""

FINAL_READINESS_SUMMARY_SCHEMA = "pico.final_readiness_summary.v1"

READINESS_REASONS = {
    "changed_paths_without_verification": (
        "hard",
        "Files changed, but no successful verification was recorded.",
    ),
    "failed_verification": ("hard", "The latest verification command failed."),
    "governance_denial": (
        "hard",
        "A runtime governance decision denied a requested tool action.",
    ),
    "partial_success_workspace_changed": (
        "hard",
        "A tool partially succeeded and changed the workspace.",
    ),
    "unresolved_high_priority_todo": (
        "soft",
        "A current-run high priority todo is still unresolved.",
    ),
    "context_pressure_without_reduction": (
        "soft",
        "Context pressure is high and no successful reduction was recorded.",
    ),
}


def reason_severity(reason):
    return READINESS_REASONS.get(str(reason), ("soft", str(reason)))[0]


def reason_message(reason):
    return READINESS_REASONS.get(str(reason), ("soft", str(reason)))[1]
