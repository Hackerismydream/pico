from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pico.config.pico import MaintenanceConfig
from pico.maintenance import (
    GitMaintenanceRunner,
    MaintenanceCoordinator,
    MaintenanceJob,
    MaintenanceOutcome,
    MaintenanceState,
    build_maintenance_coordinator,
)
from pico.spine import ChatType, Origin, Source, TurnRequest


class _Runner:
    def __init__(self, outcome: MaintenanceOutcome | None = None, progress: tuple[str, ...] = ()) -> None:
        self.calls = []
        self.outcome = outcome
        self.progress = progress

    async def run(self, job, progress=None):
        self.calls.append(job)
        for stage in self.progress:
            await progress(stage)
        if self.outcome is None:
            raise AssertionError("runner should not start")
        return self.outcome


def _request(
    text: str,
    *,
    sender: str = "ou_member",
    message_id: str = "om_1",
    extras: dict | None = None,
) -> TurnRequest:
    source_extras = {"message_id": message_id, **(extras or {})}
    return TurnRequest(
        origin=Origin.USER,
        source=Source(
            channel="feishu",
            chat_id="oc_pico",
            sender_id=sender,
            chat_type=ChatType.GROUP,
            extras=source_extras,
        ),
        text=text,
    )


async def test_regular_group_message_stays_on_the_normal_gateway_path(tmp_path: Path) -> None:
    runner = _Runner()
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=runner,
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    handled = await coordinator.handle(_request("How does the Gateway work?"), send)

    assert handled is False
    assert replies == []
    assert runner.calls == []


async def test_maintainer_can_submit_idempotent_issue_proposal(tmp_path: Path) -> None:
    runner = _Runner(MaintenanceOutcome(state=MaintenanceState.BLOCKED, detail="test"))
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=runner,
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    request = _request(
        "@_user_1 /issue grep fails when context is 1",
        sender="ou_owner",
        message_id="om_issue",
        extras={
            "message_link": "https://applink.feishu.cn/client/thread/open?open_chat_id=oc_pico&open_thread_id=omt_issue"
        },
    )
    assert await coordinator.handle(request, send) is True
    assert replies[0] == (
        "Issue captured: [grep fails when context is 1]"
        "(https://applink.feishu.cn/client/thread/open?open_chat_id=oc_pico&open_thread_id=omt_issue)\n"
        "Reply to the original report with /fix when it is ready for repair."
    )
    assert "pi_" not in replies[0]
    assert runner.calls == []

    assert await coordinator.handle(request, send) is True
    assert replies[1] == replies[0]


async def test_group_member_cannot_promote_issue_proposal(tmp_path: Path) -> None:
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=_Runner(),
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    assert await coordinator.handle(_request("/issue untriaged report"), send) is True
    assert replies == ["Only a configured Pico maintainer can promote issue proposals."]


async def test_maintainer_can_promote_replied_message_without_copying_text(tmp_path: Path) -> None:
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=_Runner(),
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    request = _request(
        "@_user_1 /issue",
        sender="ou_owner",
        extras={"quoted_text": "grep context fails through registry", "parent_message_id": "om_report"},
    )
    assert await coordinator.handle(request, send) is True
    assert replies[0].startswith("Issue captured: grep context fails through registry")


async def test_maintainer_can_start_fix_by_replying_to_captured_issue(tmp_path: Path) -> None:
    runner = _Runner(MaintenanceOutcome(state=MaintenanceState.BLOCKED, detail="test"))
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=runner,
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    issue_request = _request(
        "/issue",
        sender="ou_owner",
        message_id="om_issue_command",
        extras={
            "quoted_text": "grep context fails through registry",
            "parent_message_id": "om_report",
        },
    )
    assert await coordinator.handle(issue_request, send) is True

    fix_request = _request(
        "/fix",
        sender="ou_owner",
        message_id="om_fix_command",
        extras={"parent_message_id": "om_report"},
    )
    assert await coordinator.handle(fix_request, send) is True
    await coordinator.wait_idle()

    assert len(runner.calls) == 1
    assert runner.calls[0].issue_summary == "grep context fails through registry"
    assert replies[1] == "Repair started: grep context fails through registry."
    assert "pm_" not in replies[1]


async def test_non_maintainer_cannot_start_fix_job(tmp_path: Path) -> None:
    runner = _Runner()
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=runner,
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    handled = await coordinator.handle(_request("/fix #123"), send)

    assert handled is True
    assert replies == ["Only a configured Pico maintainer can start /fix jobs."]
    assert runner.calls == []


async def test_maintainer_fix_runs_once_and_reports_candidate(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate_report = candidate_dir / "CANDIDATE.md"
    candidate_patch = candidate_dir / "candidate.patch"
    candidate_report.write_text("candidate report", encoding="utf-8")
    candidate_patch.write_text("candidate patch", encoding="utf-8")
    runner = _Runner(
        MaintenanceOutcome(
            state=MaintenanceState.CANDIDATE_READY,
            base_commit="abc123",
            candidate_dir=candidate_dir,
            changed_files=("pico/example.py",),
        ),
        progress=("repairing", "repair checks", "clean verification"),
    )
    config = MaintenanceConfig(
        enabled=True,
        allowed_chats=["oc_pico"],
        maintainers=["ou_owner"],
    )
    coordinator = MaintenanceCoordinator(config, state_dir=tmp_path, runner=runner)
    replies: list[tuple[str, tuple[Path, ...]]] = []

    async def send(content: str, media: tuple[Path, ...] = ()) -> None:
        replies.append((content, media))

    request = _request("/fix #123", sender="ou_owner", message_id="om_same")
    assert await coordinator.handle(request, send) is True
    await coordinator.wait_idle()
    assert len(runner.calls) == 1
    assert runner.calls[0].issue_ref == "#123"
    assert runner.calls[0].source_message_id == "om_same"
    assert replies[0][0] == "Repair started: #123."
    assert [content for content, _media in replies if "Stage:" in content] == [
        "#123 - Stage: repairing.",
        "#123 - Stage: repair checks.",
        "#123 - Stage: clean verification.",
    ]
    assert replies[-1][0] == (
        "Candidate ready: #123\n"
        "Base revision: abc123\n"
        "Changed files: pico/example.py\n"
        "The review report and patch are attached."
    )
    assert replies[-1][1] == (candidate_report, candidate_patch)
    assert "pm_" not in replies[-1][0]
    assert str(tmp_path) not in replies[-1][0]

    restarted = MaintenanceCoordinator(config, state_dir=tmp_path, runner=runner)
    duplicate_replies: list[str] = []

    async def send_duplicate(content: str) -> None:
        duplicate_replies.append(content)

    assert await restarted.handle(request, send_duplicate) is True
    await restarted.wait_idle()
    assert len(runner.calls) == 1
    assert duplicate_replies == ["Repair already exists for #123 (candidate_ready)."]


async def test_failed_verification_does_not_attach_unverified_patch(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "CANDIDATE.md").write_text("failed report", encoding="utf-8")
    (candidate_dir / "candidate.patch").write_text("unverified patch", encoding="utf-8")
    runner = _Runner(
        MaintenanceOutcome(
            state=MaintenanceState.VERIFICATION_FAILED,
            base_commit="abc123",
            candidate_dir=candidate_dir,
            changed_files=("pico/example.py",),
            detail="tests failed",
        )
    )
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(enabled=True, allowed_chats=["oc_pico"], maintainers=["ou_owner"]),
        state_dir=tmp_path,
        runner=runner,
    )
    replies: list[tuple[str, tuple[Path, ...]]] = []

    async def send(content: str, media: tuple[Path, ...] = ()) -> None:
        replies.append((content, media))

    assert await coordinator.handle(_request("/fix #123", sender="ou_owner"), send) is True
    await coordinator.wait_idle()

    assert replies[-1][0].startswith("Verification failed: #123")
    assert replies[-1][1] == ()


async def test_gateway_restart_marks_orphaned_running_job_blocked(tmp_path: Path) -> None:
    from pico.maintenance.store import MaintenanceStore

    store = MaintenanceStore(tmp_path / "maintenance.db")
    job, _created = store.create_or_get(
        source_message_id="om_orphan",
        issue_ref="#123",
        chat_id="oc_pico",
        sender_id="ou_owner",
    )
    store.mark_running(job.job_id)
    store.close()

    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=_Runner(),
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    request = _request("/fix #123", sender="ou_owner", message_id="om_orphan")
    assert await coordinator.handle(request, send) is True
    assert replies == ["Repair already exists for #123 (blocked)."]


async def test_feishu_mention_prefix_still_routes_fix_command(tmp_path: Path) -> None:
    runner = _Runner(MaintenanceOutcome(state=MaintenanceState.BLOCKED, detail="test"))
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=runner,
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    request = _request("@_user_1 /fix #123", sender="ou_owner")
    assert await coordinator.handle(request, send) is True
    await coordinator.wait_idle()
    assert len(runner.calls) == 1
    assert runner.calls[0].issue_ref == "#123"


async def test_fix_rejects_untrusted_issue_reference(tmp_path: Path) -> None:
    runner = _Runner()
    coordinator = MaintenanceCoordinator(
        MaintenanceConfig(
            enabled=True,
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
        ),
        state_dir=tmp_path,
        runner=runner,
    )
    replies: list[str] = []

    async def send(content: str) -> None:
        replies.append(content)

    assert await coordinator.handle(_request("/fix ../../private", sender="ou_owner"), send) is True
    assert replies == ["Usage: /fix <issue number, proposal ID, or GitHub issue URL>"]
    assert runner.calls == []


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "pico@example.com")
    _git(path, "config", "user.name", "Pico Test")
    (path / "behavior.txt").write_text("broken\n", encoding="utf-8")
    _git(path, "add", "behavior.txt")
    _git(path, "commit", "-m", "test: seed repository")
    return path


async def test_runner_replays_patch_and_writes_candidate_packet(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")

    def agent_command(_job, worktree: Path) -> list[str]:
        script = "from pathlib import Path; Path('behavior.txt').write_text('fixed\\n')"
        return [sys.executable, "-c", script]

    runner = GitMaintenanceRunner(
        repository=repo,
        base_ref="main",
        state_dir=tmp_path / "state",
        acceptance_commands=['test "$(cat behavior.txt)" = fixed'],
        agent_command=agent_command,
        agent_timeout_seconds=30,
        command_timeout_seconds=30,
    )
    job = MaintenanceJob("pm_test", "om_test", "#123", "oc_pico", "ou_owner")
    stages: list[str] = []

    async def progress(stage: str) -> None:
        stages.append(stage)

    outcome = await runner.run(job, progress)

    assert outcome.state is MaintenanceState.CANDIDATE_READY
    assert outcome.base_commit == _git(repo, "rev-parse", "main")
    assert outcome.changed_files == ("behavior.txt",)
    assert outcome.candidate_dir is not None
    assert stages == ["base locked", "reproducing and editing", "repair checks", "clean verification"]
    assert (outcome.candidate_dir / "candidate.patch").read_text(encoding="utf-8")
    manifest = json.loads((outcome.candidate_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "candidate_ready"
    assert manifest["repair_checks"][0]["exit_code"] == 0
    assert manifest["verification_checks"][0]["exit_code"] == 0
    summary = (outcome.candidate_dir / "CANDIDATE.md").read_text(encoding="utf-8")
    assert 'test "$(cat behavior.txt)" = fixed' in summary
    assert "Repair exit: `0`" in summary
    assert "Verifier exit: `0`" in summary
    assert not (tmp_path / "state" / "runs" / "pm_test" / "repair").exists()
    assert not (tmp_path / "state" / "runs" / "pm_test" / "verify").exists()


async def test_runner_keeps_patch_but_fails_closed_when_clean_verifier_fails(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")

    def agent_command(_job, worktree: Path) -> list[str]:
        script = "from pathlib import Path; Path('behavior.txt').write_text('fixed\\n')"
        return [sys.executable, "-c", script]

    runner = GitMaintenanceRunner(
        repository=repo,
        base_ref="main",
        state_dir=tmp_path / "state",
        acceptance_commands=['test "$PICO_MAINTENANCE_PHASE" = repair'],
        agent_command=agent_command,
        agent_timeout_seconds=30,
        command_timeout_seconds=30,
    )

    outcome = await runner.run(MaintenanceJob("pm_fail", "om_fail", "#9", "oc_pico", "ou_owner"))

    assert outcome.state is MaintenanceState.VERIFICATION_FAILED
    assert outcome.candidate_dir is not None
    assert (outcome.candidate_dir / "candidate.patch").exists()
    manifest = json.loads((outcome.candidate_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "verification_failed"
    assert manifest["repair_checks"][0]["exit_code"] == 0
    assert manifest["verification_checks"][0]["exit_code"] != 0


async def test_runner_rejects_temporary_reproduction_files(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")

    def agent_command(_job, _worktree: Path) -> list[str]:
        script = (
            "from pathlib import Path; "
            "Path('behavior.txt').write_text('fixed\\n'); "
            "Path('.scratch_repro.py').write_text('temporary\\n')"
        )
        return [sys.executable, "-c", script]

    runner = GitMaintenanceRunner(
        repository=repo,
        base_ref="main",
        state_dir=tmp_path / "state",
        acceptance_commands=["true"],
        agent_command=agent_command,
        agent_timeout_seconds=30,
        command_timeout_seconds=30,
    )

    outcome = await runner.run(MaintenanceJob("pm_scratch", "om_scratch", "#1", "oc_pico", "ou_owner"))

    assert outcome.state is MaintenanceState.VERIFICATION_FAILED
    assert "temporary or runtime artifacts" in outcome.detail
    assert ".scratch_repro.py" in outcome.changed_files


async def test_runner_rejects_issue_from_another_repository(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", "https://github.com/Hackerismydream/pico.git")
    called = False

    def agent_command(_job, _worktree: Path) -> list[str]:
        nonlocal called
        called = True
        return [sys.executable, "-c", "raise SystemExit(99)"]

    runner = GitMaintenanceRunner(
        repository=repo,
        base_ref="main",
        state_dir=tmp_path / "state",
        acceptance_commands=["true"],
        agent_command=agent_command,
        agent_timeout_seconds=30,
        command_timeout_seconds=30,
    )

    outcome = await runner.run(
        MaintenanceJob(
            "pm_scope",
            "om_scope",
            "https://github.com/other/project/issues/1",
            "oc_pico",
            "ou_owner",
        )
    )

    assert outcome.state is MaintenanceState.BLOCKED
    assert "outside configured repository" in outcome.detail
    assert called is False


def test_factory_fails_closed_when_enabled_configuration_is_incomplete(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allowedChats.*maintainers.*acceptanceCommands.*runnerConfig"):
        build_maintenance_coordinator(
            MaintenanceConfig(enabled=True),
            workspace=tmp_path,
            state_dir=tmp_path / "state",
        )


def test_factory_uses_private_runner_home_and_never_requires_github_credentials(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    runner_config = tmp_path / "runner.json"
    runner_config.write_text("{}", encoding="utf-8")
    state_dir = tmp_path / "state"

    coordinator = build_maintenance_coordinator(
        MaintenanceConfig(
            enabled=True,
            repository=str(repo),
            allowed_chats=["oc_pico"],
            maintainers=["ou_owner"],
            acceptance_commands=["true"],
            runner_config=str(runner_config),
        ),
        workspace=repo,
        state_dir=state_dir,
    )

    assert coordinator is not None
    assert state_dir.stat().st_mode & 0o777 == 0o700
    private_home = state_dir / "runner-home"
    assert private_home.stat().st_mode & 0o777 == 0o700
    assert coordinator.runner.agent_environment["HOME"] == str(private_home)
    assert coordinator.runner.agent_environment["PICO_HOME"] == str(private_home / ".pico")
    assert "GH_TOKEN" not in coordinator.runner.agent_environment
    assert "GITHUB_TOKEN" not in coordinator.runner.agent_environment
    command = coordinator.runner.agent_command(
        MaintenanceJob("pm_test", "om_test", "#1", "oc_pico", "ou_owner"),
        repo,
    )
    assert "--workspace" not in command


async def test_runner_kills_agent_process_when_job_is_cancelled(tmp_path: Path, monkeypatch) -> None:
    class Process:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True
            self.returncode = -9

    process = Process()

    async def create_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    runner = GitMaintenanceRunner(
        repository=tmp_path,
        base_ref="main",
        state_dir=tmp_path / "state",
        acceptance_commands=["true"],
        agent_command=lambda _job, _worktree: ["agent"],
        agent_timeout_seconds=30,
        command_timeout_seconds=30,
    )

    task = asyncio.create_task(runner._run_exec(("agent",), cwd=tmp_path, timeout=30))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.killed is True
    assert process.waited is True
