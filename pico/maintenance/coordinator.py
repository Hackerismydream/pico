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

_FIX_COMMAND = re.compile(r"^/fix(?:\s+(?P<issue>\S+))?\s*$", re.IGNORECASE)
_ISSUE_COMMAND = re.compile(r"^/issue(?:\s+(?P<summary>.+?))?\s*$", re.IGNORECASE | re.DOTALL)
_FEISHU_MENTION_PREFIX = re.compile(r"^(?:@_user_\d+\s*)+")
_ISSUE_REF = re.compile(r"(?:#?[1-9]\d*|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9]\d*)")
_ISSUE_PROPOSAL_REF = re.compile(r"pi_[0-9a-f]{12}")


def _issue_title(summary: str, limit: int = 120) -> str:
    title = " ".join(summary.split()).replace("[", "").replace("]", "")
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def _issue_captured_message(summary: str, message_link: str) -> str:
    title = _issue_title(summary)
    issue = f"[{title}]({message_link})" if message_link.startswith("https://applink.feishu.cn/") else title
    return f"Issue captured: {issue}\nReply to the original report with /fix when it is ready for repair."


class MaintenanceJobRunner(Protocol):
    async def run(
        self,
        job: MaintenanceJob,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> MaintenanceOutcome: ...


class MaintenanceReplySink(Protocol):
    async def __call__(self, content: str, media: tuple[Path, ...] = ()) -> None: ...


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
        send: MaintenanceReplySink,
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
        issue_ref = match.group("issue") or ""
        issue_summary = ""
        if not issue_ref:
            parent_message_id = str(req.source.extras.get("parent_message_id") or "")
            proposal = self._store.get_proposal_by_source_message(parent_message_id)
            if proposal is None:
                await send("Reply to a captured issue with /fix, or use /fix <GitHub issue>.")
                return True
            issue_ref = proposal.proposal_id
            issue_summary = proposal.summary
        elif _ISSUE_PROPOSAL_REF.fullmatch(issue_ref) is not None:
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
            title = _issue_title(job.issue_summary or job.issue_ref)
            await send(f"Repair already exists for {title} ({job.state.value}).")
            return True
        await send(f"Repair started: {_issue_title(issue_summary or issue_ref)}.")
        task = asyncio.create_task(self._execute(job, send))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _handle_issue_proposal(
        self,
        req: TurnRequest,
        summary: str,
        send: MaintenanceReplySink,
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
        proposal_source = str(req.source.extras.get("parent_message_id") or message_id)
        proposal, _created = self._store.create_or_get_proposal(
            source_message_id=proposal_source,
            summary=summary,
            chat_id=req.source.chat_id,
            sender_id=req.source.sender_id,
        )
        message_link = str(req.source.extras.get("message_link") or "")
        await send(_issue_captured_message(proposal.summary, message_link))
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
        send: MaintenanceReplySink,
    ) -> None:
        self._store.mark_running(job.job_id)
        current_stage = "starting"
        title = _issue_title(job.issue_summary or job.issue_ref)

        async def safe_send(content: str, media: tuple[Path, ...] = ()) -> None:
            try:
                if media:
                    await send(content, media)
                else:
                    await send(content)
            except Exception as exc:
                logger.warning("Maintenance job {} progress delivery failed: {}", job.job_id, exc)

        async def progress(stage: str) -> None:
            nonlocal current_stage
            current_stage = stage
            await safe_send(f"{title} - Stage: {stage}.")

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self.config.progress_interval_seconds)
                await safe_send(f"{title} is still running - Stage: {current_stage}.")

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
            base = outcome.base_commit or "unknown"
            attachments: tuple[Path, ...] = ()
            if outcome.state is MaintenanceState.CANDIDATE_READY and outcome.candidate_dir is not None:
                attachments = tuple(
                    path
                    for name in ("CANDIDATE.md", "candidate.patch")
                    if (path := outcome.candidate_dir / name).is_file()
                )
            if outcome.state is MaintenanceState.CANDIDATE_READY:
                content = (
                    f"Candidate ready: {title}\n"
                    f"Base revision: {base}\n"
                    f"Changed files: {files}\n"
                    "The review report and patch are attached."
                )
            elif outcome.state is MaintenanceState.VERIFICATION_FAILED:
                content = (
                    f"Verification failed: {title}\n"
                    f"Base revision: {base}\n"
                    f"Changed files: {files}\n"
                    f"Reason: {outcome.detail or 'acceptance checks did not pass'}."
                )
            else:
                content = f"Repair blocked: {title}\nReason: {outcome.detail or 'no detail available'}."
            await safe_send(content, attachments)
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
