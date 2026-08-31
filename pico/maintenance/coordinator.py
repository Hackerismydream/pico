from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from loguru import logger

from pico.config.pico import MaintenanceConfig
from pico.maintenance.models import MaintenanceJob, MaintenanceOutcome, MaintenanceState
from pico.maintenance.store import MaintenanceStore
from pico.spine import TurnRequest

_FIX_COMMAND = re.compile(r"^/fix\s+(?P<issue>\S+)\s*$", re.IGNORECASE)
_ISSUE_COMMAND = re.compile(r"^/issue(?:\s+(?P<summary>.+?))?\s*$", re.IGNORECASE | re.DOTALL)
_FEISHU_MENTION_PREFIX = re.compile(r"^(?:@_user_\d+\s*)+")
_ISSUE_REF = re.compile(r"(?:#?[1-9]\d*|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9]\d*)")
_ISSUE_PROPOSAL_REF = re.compile(r"pi_[0-9a-f]{12}")


class MaintenanceJobRunner(Protocol):
    async def run(
        self,
        job: MaintenanceJob,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> MaintenanceOutcome: ...


class MaintenanceCoordinator:
    def __init__(
        self,
        config: MaintenanceConfig,
        *,
        state_dir: Path,
        runner: MaintenanceJobRunner,
    ) -> None:
        self.config = config
        self.state_dir = state_dir
        self.runner = runner
        self._store = MaintenanceStore(state_dir / "maintenance.db")
        self._store.mark_unfinished_blocked()
        self._tasks: set[asyncio.Task[None]] = set()

    def is_maintainer(self, req: TurnRequest) -> bool:
        return req.source.chat_id in self.config.allowed_chats and req.source.sender_id in self.config.maintainers

    async def handle(
        self,
        req: TurnRequest,
        send: Callable[[str], Awaitable[None]],
    ) -> bool:
        text = req.text.strip()
        if req.source.channel == "feishu":
            text = _FEISHU_MENTION_PREFIX.sub("", text).strip()
        if not self.config.enabled:
            return False
        issue_match = _ISSUE_COMMAND.fullmatch(text)
        if issue_match is not None:
            return await self._handle_issue_proposal(req, (issue_match.group("summary") or "").strip(), send)
        match = _FIX_COMMAND.fullmatch(text)
        if match is None:
            return False
        if req.source.chat_id not in self.config.allowed_chats:
            await send("This chat is not authorized to start Pico maintenance jobs.")
            return True
        if not self.is_maintainer(req):
            await send("Only a configured Pico maintainer can start /fix jobs.")
            return True
        issue_ref = match.group("issue")
        issue_summary = ""
        if _ISSUE_PROPOSAL_REF.fullmatch(issue_ref) is not None:
            proposal = self._store.get_proposal(issue_ref)
            if proposal is None:
                await send(f"Issue proposal {issue_ref} was not found.")
                return True
            issue_summary = proposal.summary
        elif _ISSUE_REF.fullmatch(issue_ref) is None:
            await send("Usage: /fix <issue number, proposal ID, or GitHub issue URL>")
            return True
        message_id = str(req.source.extras.get("message_id") or "")
        if not message_id:
            await send("Cannot start /fix without a stable source message ID.")
            return True
        job, created = self._store.create_or_get(
            source_message_id=message_id,
            issue_ref=issue_ref,
            chat_id=req.source.chat_id,
            sender_id=req.source.sender_id,
            issue_summary=issue_summary,
        )
        if not created:
            await send(f"Maintenance job {job.job_id} already exists ({job.state.value}).")
            return True
        await send(f"Accepted maintenance job {job.job_id} for {issue_ref}.")
        task = asyncio.create_task(self._execute(job, send))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _handle_issue_proposal(
        self,
        req: TurnRequest,
        summary: str,
        send: Callable[[str], Awaitable[None]],
    ) -> bool:
        if req.source.chat_id not in self.config.allowed_chats:
            await send("This chat is not authorized to submit Pico issue proposals.")
            return True
        if not self.is_maintainer(req):
            await send("Only a configured Pico maintainer can promote issue proposals.")
            return True
        if not summary:
            summary = str(req.source.extras.get("quoted_text") or "").strip()
        if not summary:
            await send("Reply to a user message with /issue, or use /issue <description>.")
            return True
        if len(summary) > 4000:
            await send("Issue proposal is too long; keep it within 4000 characters.")
            return True
        message_id = str(req.source.extras.get("message_id") or "")
        if not message_id:
            await send("Cannot submit an issue proposal without a stable source message ID.")
            return True
        proposal, created = self._store.create_or_get_proposal(
            source_message_id=message_id,
            summary=summary,
            chat_id=req.source.chat_id,
            sender_id=req.source.sender_id,
        )
        if not created:
            await send(f"Issue proposal {proposal.proposal_id} already exists.")
            return True
        await send(
            f"Recorded issue proposal {proposal.proposal_id}. "
            "A maintainer must confirm it before GitHub publication or /fix."
        )
        return True

    async def wait_idle(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks))

    async def close(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._store.close()

    async def _execute(
        self,
        job: MaintenanceJob,
        send: Callable[[str], Awaitable[None]],
    ) -> None:
        self._store.mark_running(job.job_id)
        current_stage = "starting"

        async def safe_send(content: str) -> None:
            try:
                await send(content)
            except Exception as exc:
                logger.warning("Maintenance job {} progress delivery failed: {}", job.job_id, exc)

        async def progress(stage: str) -> None:
            nonlocal current_stage
            current_stage = stage
            await safe_send(f"Maintenance job {job.job_id} - Stage: {stage}.")

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self.config.progress_interval_seconds)
                await safe_send(f"Maintenance job {job.job_id} is still running - Stage: {current_stage}.")

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            try:
                outcome = await self.runner.run(job, progress)
            except asyncio.CancelledError:
                outcome = MaintenanceOutcome(MaintenanceState.BLOCKED, detail="Gateway stopped during maintenance job")
                self._store.record_outcome(job.job_id, outcome)
                raise
            except Exception as exc:
                outcome = MaintenanceOutcome(MaintenanceState.BLOCKED, detail=str(exc))
            self._store.record_outcome(job.job_id, outcome)
            files = ", ".join(outcome.changed_files) if outcome.changed_files else "none"
            candidate = outcome.candidate_dir.name if outcome.candidate_dir is not None else "none"
            base = outcome.base_commit or "unknown"
            await safe_send(
                f"Maintenance job {job.job_id}: {outcome.state.value}; base: {base}; "
                f"changed files: {files}; candidate: {candidate}."
            )
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
