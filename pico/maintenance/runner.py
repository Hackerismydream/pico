from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from pico.maintenance.models import MaintenanceJob, MaintenanceOutcome, MaintenanceState

_ISSUE_PROPOSAL_REF = re.compile(r"pi_[0-9a-f]{12}")
_RUNTIME_ARTIFACT_ROOTS = {"agent_memory", "memory", "sessions", "telemetry", "user_memory"}


@dataclass(frozen=True)
class CommandReceipt:
    command: str
    exit_code: int
    log: str


AgentCommand = Callable[[MaintenanceJob, Path], Sequence[str]]


class GitMaintenanceRunner:
    def __init__(
        self,
        *,
        repository: Path,
        base_ref: str,
        state_dir: Path,
        acceptance_commands: Sequence[str],
        agent_command: AgentCommand,
        agent_timeout_seconds: int,
        command_timeout_seconds: int,
        agent_environment: dict[str, str] | None = None,
    ) -> None:
        self.repository = repository.resolve()
        self.base_ref = base_ref
        self.state_dir = state_dir.resolve()
        self.acceptance_commands = tuple(acceptance_commands)
        self.agent_command = agent_command
        self.agent_timeout_seconds = agent_timeout_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self.agent_environment = dict(agent_environment or {})

    async def run(self, job: MaintenanceJob) -> MaintenanceOutcome:
        run_root = self.state_dir / "runs" / job.job_id
        repair = run_root / "repair"
        verify = run_root / "verify"
        candidate = self.state_dir / "candidates" / job.job_id
        candidate.mkdir(parents=True, exist_ok=True)
        base_commit = await self._git_text("rev-parse", "--verify", f"{self.base_ref}^{{commit}}")
        issue_ref, issue_error = await self._validated_issue_ref(job)
        if issue_error:
            manifest = {
                "schema": "pico.maintenance.candidate.v1",
                "job_id": job.job_id,
                "issue": job.issue_ref,
                "issue_summary": job.issue_summary,
                "repository": str(self.repository),
                "base_commit": base_commit,
                "state": MaintenanceState.BLOCKED.value,
                "changed_files": [],
                "repair_checks": [],
                "verification_checks": [],
            }
            return self._finish(
                candidate,
                manifest,
                MaintenanceState.BLOCKED,
                base_commit,
                (),
                issue_error,
            )
        job = replace(job, issue_ref=issue_ref)
        manifest: dict = {
            "schema": "pico.maintenance.candidate.v1",
            "job_id": job.job_id,
            "issue": job.issue_ref,
            "issue_summary": job.issue_summary,
            "repository": str(self.repository),
            "base_commit": base_commit,
            "state": MaintenanceState.BLOCKED.value,
            "changed_files": [],
            "repair_checks": [],
            "verification_checks": [],
        }
        patch_path = candidate / "candidate.patch"
        changed_files: tuple[str, ...] = ()
        state = MaintenanceState.BLOCKED
        detail = ""
        repair_added = verify_added = False
        try:
            await self._prepare_worktree(repair, base_commit)
            repair_added = True
            agent_receipt = await self._run_exec(
                tuple(self.agent_command(job, repair)),
                cwd=repair,
                timeout=self.agent_timeout_seconds,
                env=self.agent_environment,
                inherit_env=False,
            )
            (candidate / "agent.log").write_text(agent_receipt.log, encoding="utf-8")
            manifest["agent_exit_code"] = agent_receipt.exit_code
            if agent_receipt.exit_code != 0:
                detail = f"Agent exited with {agent_receipt.exit_code}"
                return self._finish(candidate, manifest, state, base_commit, changed_files, detail)

            await self._run_exec(("git", "add", "-N", "--", "."), cwd=repair, timeout=30)
            patch = await self._git_bytes("-C", str(repair), "diff", "--binary", "HEAD")
            patch_path.write_bytes(patch)
            names = await self._git_text("-C", str(repair), "diff", "--name-only", "HEAD")
            changed_files = tuple(line for line in names.splitlines() if line)
            if not patch or not changed_files:
                detail = "Agent produced no patch"
                return self._finish(candidate, manifest, state, base_commit, changed_files, detail)
            rejected_files = tuple(path for path in changed_files if self._is_runtime_or_scratch_path(path))
            if rejected_files:
                manifest["policy_rejected_files"] = list(rejected_files)
                state = MaintenanceState.VERIFICATION_FAILED
                detail = "Candidate contains temporary or runtime artifacts: " + ", ".join(rejected_files)
                return self._finish(candidate, manifest, state, base_commit, changed_files, detail)

            repair_checks = await self._run_checks(repair, candidate, phase="repair")
            manifest["repair_checks"] = [asdict(item) for item in repair_checks]
            if any(item.exit_code != 0 for item in repair_checks):
                state = MaintenanceState.VERIFICATION_FAILED
                detail = "Repair worktree checks failed"
                return self._finish(candidate, manifest, state, base_commit, changed_files, detail)

            await self._prepare_worktree(verify, base_commit)
            verify_added = True
            apply_receipt = await self._run_exec(
                ("git", "apply", "--binary", str(patch_path)),
                cwd=verify,
                timeout=60,
            )
            manifest["apply_exit_code"] = apply_receipt.exit_code
            (candidate / "verify-apply.log").write_text(apply_receipt.log, encoding="utf-8")
            if apply_receipt.exit_code != 0:
                state = MaintenanceState.VERIFICATION_FAILED
                detail = "Candidate patch did not apply to the clean base"
                return self._finish(candidate, manifest, state, base_commit, changed_files, detail)

            verification_checks = await self._run_checks(verify, candidate, phase="verify")
            manifest["verification_checks"] = [asdict(item) for item in verification_checks]
            if any(item.exit_code != 0 for item in verification_checks):
                state = MaintenanceState.VERIFICATION_FAILED
                detail = "Clean verifier checks failed"
            else:
                state = MaintenanceState.CANDIDATE_READY
                detail = "Patch applied to the clean base and every configured check passed"
            return self._finish(candidate, manifest, state, base_commit, changed_files, detail)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = str(exc)
            return self._finish(candidate, manifest, MaintenanceState.BLOCKED, base_commit, changed_files, detail)
        finally:
            if verify_added:
                await self._remove_worktree(verify)
            if repair_added:
                await self._remove_worktree(repair)
            if run_root.exists():
                shutil.rmtree(run_root, ignore_errors=True)

    async def _prepare_worktree(self, path: Path, base_commit: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.rmtree(path)
        receipt = await self._run_exec(
            ("git", "worktree", "add", "--detach", str(path), base_commit),
            cwd=self.repository,
            timeout=60,
        )
        if receipt.exit_code != 0:
            raise RuntimeError(receipt.log)

    async def _remove_worktree(self, path: Path) -> None:
        await self._run_exec(
            ("git", "worktree", "remove", "--force", str(path)),
            cwd=self.repository,
            timeout=60,
        )

    async def _run_checks(self, worktree: Path, candidate: Path, *, phase: str) -> list[CommandReceipt]:
        receipts: list[CommandReceipt] = []
        for index, command in enumerate(self.acceptance_commands, start=1):
            receipt = await self._run_exec(
                ("/bin/sh", "-lc", command),
                cwd=worktree,
                timeout=self.command_timeout_seconds,
                env={**self.agent_environment, "PICO_MAINTENANCE_PHASE": phase},
                display=command,
                inherit_env=False,
            )
            log_name = f"{phase}-check-{index}.log"
            (candidate / log_name).write_text(receipt.log, encoding="utf-8")
            receipts.append(CommandReceipt(receipt.command, receipt.exit_code, log_name))
        return receipts

    def _finish(
        self,
        candidate: Path,
        manifest: dict,
        state: MaintenanceState,
        base_commit: str,
        changed_files: tuple[str, ...],
        detail: str,
    ) -> MaintenanceOutcome:
        manifest.update(
            {
                "state": state.value,
                "changed_files": list(changed_files),
                "detail": detail,
            }
        )
        (candidate / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        check_lines = []
        repair_checks = manifest.get("repair_checks", [])
        verification_checks = manifest.get("verification_checks", [])
        for index, repair_check in enumerate(repair_checks):
            verifier_exit = verification_checks[index]["exit_code"] if index < len(verification_checks) else "not run"
            check_lines.append(
                f"- `{repair_check['command']}`; Repair exit: `{repair_check['exit_code']}`; "
                f"Verifier exit: `{verifier_exit}`"
            )
        checks = "\n".join(check_lines) or "- none"
        (candidate / "CANDIDATE.md").write_text(
            f"# Maintenance candidate {manifest['job_id']}\n\n"
            f"- Issue: `{manifest['issue']}`\n"
            f"- Issue summary: {manifest.get('issue_summary') or 'not provided'}\n"
            f"- Base revision: `{base_commit}`\n"
            f"- State: `{state.value}`\n"
            f"- Changed files: {', '.join(changed_files) or 'none'}\n"
            f"- Patch: `candidate.patch`\n"
            f"- Verdict: {detail}\n\n"
            f"## Checks\n\n{checks}\n",
            encoding="utf-8",
        )
        return MaintenanceOutcome(
            state=state,
            base_commit=base_commit,
            candidate_dir=candidate,
            changed_files=changed_files,
            detail=detail,
        )

    async def _validated_issue_ref(self, job: MaintenanceJob) -> tuple[str, str]:
        issue_ref = job.issue_ref
        if _ISSUE_PROPOSAL_REF.fullmatch(issue_ref):
            if not job.issue_summary:
                return issue_ref, "Local issue proposal has no persisted summary"
            return issue_ref, ""
        if re.fullmatch(r"#?[1-9]\d*", issue_ref):
            return issue_ref if issue_ref.startswith("#") else f"#{issue_ref}", ""
        match = re.fullmatch(
            r"https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/issues/(?P<number>[1-9]\d*)",
            issue_ref,
        )
        if match is None:
            return issue_ref, "Invalid GitHub issue reference"
        remote = await self._git_text("config", "--get", "remote.origin.url")
        remote_match = re.search(
            r"github\.com[/:](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$",
            remote,
        )
        if remote_match is None:
            return issue_ref, "Configured repository has no canonical GitHub origin"
        requested = (match.group("owner").lower(), match.group("repo").lower())
        configured = (remote_match.group("owner").lower(), remote_match.group("repo").lower())
        if requested != configured:
            return issue_ref, "Issue is outside configured repository"
        return issue_ref, ""

    async def _git_text(self, *args: str) -> str:
        receipt = await self._run_exec(("git", *args), cwd=self.repository, timeout=60)
        if receipt.exit_code != 0:
            raise RuntimeError(receipt.log)
        return receipt.log.strip()

    async def _git_bytes(self, *args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.repository,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RuntimeError("git command timed out after 60s") from exc
        if process.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace"))
        return stdout

    async def _run_exec(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout: int,
        env: dict[str, str] | None = None,
        display: str | None = None,
        inherit_env: bool = True,
    ) -> CommandReceipt:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**(os.environ if inherit_env else self._safe_environment()), **(env or {})},
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return CommandReceipt(display or " ".join(argv), -1, f"Timed out after {timeout}s\n")
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        log = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        return CommandReceipt(display or " ".join(argv), process.returncode, log)

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "TMPDIR")
        return {key: value for key in allowed if (value := os.environ.get(key)) is not None}

    @staticmethod
    def _is_runtime_or_scratch_path(path: str) -> bool:
        parts = Path(path).parts
        return bool(parts) and (
            parts[0] in _RUNTIME_ARTIFACT_ROOTS or any(part.startswith(".scratch") for part in parts)
        )
