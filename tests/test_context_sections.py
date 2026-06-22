from pico.core.context_sections import (
    DEFAULT_SECTION_BUDGETS,
    MIN_SECTION_BUDGETS,
    REDUCTION_ORDER,
    SECTION_ORDER,
    SECTION_POLICIES,
    ContextSectionPolicy,
    reduction_order,
    section_budgets,
    section_floors,
    section_order,
)
from pico.core.context_manager import ContextManager


def test_context_section_policy_registry_preserves_order_and_budget_data():
    assert SECTION_ORDER == ("prefix", "memory", "skills", "relevant_memory", "history", "current_request")
    assert [policy.name for policy in SECTION_POLICIES] == list(SECTION_ORDER)
    assert all(isinstance(policy, ContextSectionPolicy) for policy in SECTION_POLICIES)
    assert DEFAULT_SECTION_BUDGETS == {
        "prefix": 12000,
        "memory": 8000,
        "skills": 4000,
        "relevant_memory": 6000,
        "history": 30000,
    }
    assert MIN_SECTION_BUDGETS == {
        "prefix": 4000,
        "memory": 1200,
        "skills": 600,
        "relevant_memory": 1000,
        "history": 6000,
    }
    assert REDUCTION_ORDER == ("relevant_memory", "skills", "history", "memory", "prefix")
    assert section_order() == SECTION_ORDER
    assert section_budgets() == DEFAULT_SECTION_BUDGETS
    assert section_floors() == MIN_SECTION_BUDGETS
    assert reduction_order() == REDUCTION_ORDER


def test_context_section_policy_records_sources_and_non_reducible_request():
    policies = {policy.name: policy for policy in SECTION_POLICIES}

    assert policies["prefix"].sources == ("workspace_prefix",)
    assert policies["memory"].sources == (
        "working_memory",
        "todo_ledger",
        "checkpoint_text",
        "memory_system_contract",
    )
    assert policies["skills"].sources == ("skills",)
    assert policies["relevant_memory"].sources == ("relevant_memory",)
    assert policies["history"].sources == ("history",)
    assert policies["current_request"].sources == ("current_request",)

    protected_sources = {source for policy in SECTION_POLICIES if policy.protected for source in policy.sources}
    assert protected_sources == {
        "working_memory",
        "todo_ledger",
        "checkpoint_text",
        "memory_system_contract",
        "relevant_memory",
        "history",
        "current_request",
    }
    assert policies["current_request"].budget_chars is None
    assert policies["current_request"].floor_chars is None
    assert policies["current_request"].reduction_rank is None
    assert {name: policies[name].reduction_rank for name in REDUCTION_ORDER} == {
        "relevant_memory": 0,
        "skills": 1,
        "history": 2,
        "memory": 3,
        "prefix": 4,
    }


def test_context_manager_exports_legacy_section_policy_names():
    from pico.core.context_manager import (
        DEFAULT_REDUCTION_ORDER,
        DEFAULT_SECTION_FLOORS,
        DEFAULT_SECTION_BUDGETS as LEGACY_BUDGETS,
        SECTION_ORDER as LEGACY_ORDER,
    )

    assert LEGACY_BUDGETS == DEFAULT_SECTION_BUDGETS
    assert DEFAULT_SECTION_FLOORS == MIN_SECTION_BUDGETS
    assert DEFAULT_REDUCTION_ORDER == REDUCTION_ORDER
    assert LEGACY_ORDER == SECTION_ORDER


def test_context_manager_default_floors_match_section_registry():
    manager = ContextManager(agent=object())

    assert manager.section_floors == MIN_SECTION_BUDGETS


def test_context_manager_recomputes_floors_for_mutated_custom_budgets():
    manager = ContextManager(agent=object())
    manager.section_budgets = {"prefix": 120, "memory": 120, "relevant_memory": 120, "history": 160}

    assert manager._compute_section_floors() == {
        "prefix": 30,
        "memory": 30,
        "relevant_memory": 30,
        "history": 40,
    }
