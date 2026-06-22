"""Data-only prompt section policy registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextSectionPolicy:
    name: str
    budget_chars: int | None
    floor_chars: int | None
    reduction_rank: int | None
    sources: tuple[str, ...]
    protected: bool


SECTION_ORDER = ("prefix", "memory", "skills", "relevant_memory", "history", "current_request")
REDUCTION_ORDER = ("relevant_memory", "skills", "history", "memory", "prefix")

DEFAULT_SECTION_BUDGETS = {
    "prefix": 12000,
    "memory": 8000,
    "skills": 4000,
    "relevant_memory": 6000,
    "history": 30000,
}
MIN_SECTION_BUDGETS = {
    "prefix": 4000,
    "memory": 1200,
    "skills": 600,
    "relevant_memory": 1000,
    "history": 6000,
}

_REDUCTION_RANKS = {name: rank for rank, name in enumerate(REDUCTION_ORDER)}

SECTION_POLICIES = (
    ContextSectionPolicy(
        name="prefix",
        budget_chars=DEFAULT_SECTION_BUDGETS["prefix"],
        floor_chars=MIN_SECTION_BUDGETS["prefix"],
        reduction_rank=_REDUCTION_RANKS["prefix"],
        sources=("workspace_prefix",),
        protected=False,
    ),
    ContextSectionPolicy(
        name="memory",
        budget_chars=DEFAULT_SECTION_BUDGETS["memory"],
        floor_chars=MIN_SECTION_BUDGETS["memory"],
        reduction_rank=_REDUCTION_RANKS["memory"],
        sources=("working_memory", "todo_ledger", "checkpoint_text", "memory_system_contract"),
        protected=True,
    ),
    ContextSectionPolicy(
        name="skills",
        budget_chars=DEFAULT_SECTION_BUDGETS["skills"],
        floor_chars=MIN_SECTION_BUDGETS["skills"],
        reduction_rank=_REDUCTION_RANKS["skills"],
        sources=("skills",),
        protected=False,
    ),
    ContextSectionPolicy(
        name="relevant_memory",
        budget_chars=DEFAULT_SECTION_BUDGETS["relevant_memory"],
        floor_chars=MIN_SECTION_BUDGETS["relevant_memory"],
        reduction_rank=_REDUCTION_RANKS["relevant_memory"],
        sources=("relevant_memory",),
        protected=True,
    ),
    ContextSectionPolicy(
        name="history",
        budget_chars=DEFAULT_SECTION_BUDGETS["history"],
        floor_chars=MIN_SECTION_BUDGETS["history"],
        reduction_rank=_REDUCTION_RANKS["history"],
        sources=("history",),
        protected=True,
    ),
    ContextSectionPolicy(
        name="current_request",
        budget_chars=None,
        floor_chars=None,
        reduction_rank=None,
        sources=("current_request",),
        protected=True,
    ),
)

SECTION_POLICIES_BY_NAME = {policy.name: policy for policy in SECTION_POLICIES}
CURRENT_REQUEST_SECTION = "current_request"


def section_order():
    return SECTION_ORDER


def section_budgets():
    return dict(DEFAULT_SECTION_BUDGETS)


def section_floors():
    return dict(MIN_SECTION_BUDGETS)


def reduction_order():
    return REDUCTION_ORDER
