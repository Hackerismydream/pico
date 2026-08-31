from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from pico.maintenance.models import IssueProposal, MaintenanceJob, MaintenanceOutcome, MaintenanceState


class MaintenanceStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance_jobs (
                job_id TEXT PRIMARY KEY,
                source_message_id TEXT NOT NULL UNIQUE,
                issue_ref TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                state TEXT NOT NULL,
                base_commit TEXT NOT NULL DEFAULT '',
                candidate_dir TEXT NOT NULL DEFAULT '',
                changed_files TEXT NOT NULL DEFAULT '[]',
                detail TEXT NOT NULL DEFAULT '',
                issue_summary TEXT NOT NULL DEFAULT ''
            )
            """
        )
        columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(maintenance_jobs)")}
        if "issue_summary" not in columns:
            self._connection.execute("ALTER TABLE maintenance_jobs ADD COLUMN issue_summary TEXT NOT NULL DEFAULT ''")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS issue_proposals (
                proposal_id TEXT PRIMARY KEY,
                source_message_id TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                sender_id TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def create_or_get_proposal(
        self,
        *,
        source_message_id: str,
        summary: str,
        chat_id: str,
        sender_id: str,
    ) -> tuple[IssueProposal, bool]:
        proposal_id = "pi_" + hashlib.sha256(source_message_id.encode()).hexdigest()[:12]
        try:
            self._connection.execute(
                """
                INSERT INTO issue_proposals (
                    proposal_id, source_message_id, summary, chat_id, sender_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (proposal_id, source_message_id, summary, chat_id, sender_id),
            )
            self._connection.commit()
            return IssueProposal(proposal_id, source_message_id, summary, chat_id, sender_id), True
        except sqlite3.IntegrityError:
            row = self._connection.execute(
                "SELECT * FROM issue_proposals WHERE source_message_id = ?",
                (source_message_id,),
            ).fetchone()
            if row is None:
                raise
            return (
                IssueProposal(
                    proposal_id=row["proposal_id"],
                    source_message_id=row["source_message_id"],
                    summary=row["summary"],
                    chat_id=row["chat_id"],
                    sender_id=row["sender_id"],
                ),
                False,
            )

    def create_or_get(
        self,
        *,
        source_message_id: str,
        issue_ref: str,
        chat_id: str,
        sender_id: str,
        issue_summary: str = "",
    ) -> tuple[MaintenanceJob, bool]:
        job_id = "pm_" + hashlib.sha256(source_message_id.encode()).hexdigest()[:12]
        try:
            self._connection.execute(
                """
                INSERT INTO maintenance_jobs (
                    job_id, source_message_id, issue_ref, chat_id, sender_id, state, issue_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    source_message_id,
                    issue_ref,
                    chat_id,
                    sender_id,
                    MaintenanceState.QUEUED.value,
                    issue_summary,
                ),
            )
            self._connection.commit()
            return (
                MaintenanceJob(
                    job_id=job_id,
                    source_message_id=source_message_id,
                    issue_ref=issue_ref,
                    chat_id=chat_id,
                    sender_id=sender_id,
                    issue_summary=issue_summary,
                ),
                True,
            )
        except sqlite3.IntegrityError:
            row = self._connection.execute(
                "SELECT * FROM maintenance_jobs WHERE source_message_id = ?",
                (source_message_id,),
            ).fetchone()
            if row is None:
                raise
            return self._job(row), False

    def mark_running(self, job_id: str) -> None:
        self._connection.execute(
            "UPDATE maintenance_jobs SET state = ? WHERE job_id = ?",
            (MaintenanceState.RUNNING.value, job_id),
        )
        self._connection.commit()

    def mark_unfinished_blocked(self) -> None:
        self._connection.execute(
            """
            UPDATE maintenance_jobs
            SET state = ?, detail = ?
            WHERE state IN (?, ?)
            """,
            (
                MaintenanceState.BLOCKED.value,
                "Gateway restarted before the maintenance job reached a terminal state",
                MaintenanceState.QUEUED.value,
                MaintenanceState.RUNNING.value,
            ),
        )
        self._connection.commit()

    def record_outcome(self, job_id: str, outcome: MaintenanceOutcome) -> None:
        self._connection.execute(
            """
            UPDATE maintenance_jobs
            SET state = ?, base_commit = ?, candidate_dir = ?, changed_files = ?, detail = ?
            WHERE job_id = ?
            """,
            (
                outcome.state.value,
                outcome.base_commit,
                str(outcome.candidate_dir or ""),
                json.dumps(outcome.changed_files),
                outcome.detail,
                job_id,
            ),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def get_proposal(self, proposal_id: str) -> IssueProposal | None:
        row = self._connection.execute(
            "SELECT * FROM issue_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._proposal(row)

    def get_proposal_by_source_message(self, source_message_id: str) -> IssueProposal | None:
        row = self._connection.execute(
            "SELECT * FROM issue_proposals WHERE source_message_id = ?",
            (source_message_id,),
        ).fetchone()
        if row is None:
            return None
        return self._proposal(row)

    @staticmethod
    def _proposal(row: sqlite3.Row) -> IssueProposal:
        return IssueProposal(
            proposal_id=row["proposal_id"],
            source_message_id=row["source_message_id"],
            summary=row["summary"],
            chat_id=row["chat_id"],
            sender_id=row["sender_id"],
        )

    @staticmethod
    def _job(row: sqlite3.Row) -> MaintenanceJob:
        return MaintenanceJob(
            job_id=row["job_id"],
            source_message_id=row["source_message_id"],
            issue_ref=row["issue_ref"],
            chat_id=row["chat_id"],
            sender_id=row["sender_id"],
            state=MaintenanceState(row["state"]),
            issue_summary=row["issue_summary"],
        )
