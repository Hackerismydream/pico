from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class MaintenanceState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANDIDATE_READY = "candidate_ready"
    VERIFICATION_FAILED = "verification_failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MaintenanceJob:
    job_id: str
    source_message_id: str
    issue_ref: str
    chat_id: str
    sender_id: str
    state: MaintenanceState = MaintenanceState.QUEUED
    issue_summary: str = ""


@dataclass(frozen=True)
class IssueProposal:
    proposal_id: str
    source_message_id: str
    summary: str
    chat_id: str
    sender_id: str


@dataclass(frozen=True)
class MaintenanceOutcome:
    state: MaintenanceState
    base_commit: str = ""
    candidate_dir: Path | None = None
    changed_files: tuple[str, ...] = ()
    detail: str = ""
