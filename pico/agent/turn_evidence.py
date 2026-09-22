"""从系统拥有的 ToolExecution 与 Git 状态构造 Pico Turn feedback。"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path, PurePath

from pico.agent.tools.base import ToolResult
from pico.agent.tools.execution import ToolEffect, ToolExecution


class TurnEvidenceLog:
    """收集一轮内可由 Runtime 直接观察的结构化执行收据。"""

    def __init__(
        self,
        *,
        workspace: Path,
        session_id: str,
        turn_id: str,
        trace_id: str,
        injected_skill_ids: list[str],
        referenced_skill_ids: list[str],
    ) -> None:
        self._workspace = workspace.resolve()
        self._session_id = session_id
        self._turn_id = turn_id
        self._trace_id = trace_id
        self._base_revision = repository_revision(self._workspace)
        self._injected_skill_ids = tuple(sorted(set(injected_skill_ids)))
        self._referenced_skill_ids = tuple(sorted(set(referenced_skill_ids)))
        self._tool_receipts: list[dict[str, object]] = []
        self._command_receipts: list[dict[str, object]] = []
        self._file_changes: list[dict[str, object]] = []
        self._verifications: list[dict[str, object]] = []

    def observe(self, execution: ToolExecution, *, effect: ToolEffect) -> None:
        """把一次完成的 ToolExecution 规范化为能力、结果与可选命令/文件收据。"""
        invocation = execution.invocation
        call_id = invocation.context.call_id or f"runtime-call-{len(self._tool_receipts) + 1}"
        failed = bool(getattr(execution.result, "failed", False))
        outcome = "failure" if failed else "success"
        self._tool_receipts.append(
            {
                "tool_name": invocation.name,
                "call_id": call_id,
                "capability": effect.value,
                "outcome": outcome,
                "duration_ms": max(0, round(execution.duration_ms)),
            }
        )
        receipt = execution.result.receipt if isinstance(execution.result, ToolResult) else {}
        command, exit_code = receipt.get("command"), receipt.get("exit_code")
        if isinstance(command, str) and command and type(exit_code) is int:
            self._command_receipts.append({"call_id": call_id, "command": command, "exit_code": exit_code})
            check_name = verification_name(command)
            if check_name is not None:
                self._verifications.append({"check_name": check_name, "outcome": outcome, "call_id": call_id})
        if not failed and invocation.name in {"write_file", "edit_file"}:
            path = invocation.arguments.get("path")
            relative = _relative_path(path, workspace=self._workspace)
            if relative is not None:
                self._file_changes.append({"path": relative, "change_kind": "unknown", "destination_path": None})

    def feedback(
        self,
        *,
        terminal_state: str,
        delivery_state: str,
        edited_files: list[str],
    ) -> dict[str, object]:
        """生成字段闭合的 `pico.turn-feedback.v1` 载荷。"""
        changes = {
            (str(item["path"]), str(item["change_kind"]), item["destination_path"]): item for item in self._file_changes
        }
        for path in edited_files:
            relative = _relative_path(path, workspace=self._workspace)
            if relative is not None:
                changes.setdefault(
                    (relative, "unknown", None),
                    {"path": relative, "change_kind": "unknown", "destination_path": None},
                )
        return {
            "schema": "pico.turn-feedback.v1",
            "base_revision": self._base_revision,
            "session_id": self._session_id,
            "turn_id": self._turn_id,
            "trace_id": self._trace_id,
            "terminal_state": terminal_state,
            "delivery_state": delivery_state,
            "tool_receipts": self._tool_receipts,
            "command_receipts": self._command_receipts,
            "file_changes": [changes[key] for key in sorted(changes)],
            "verifications": self._verifications,
            "injected_skill_ids": list(self._injected_skill_ids),
            "referenced_skill_ids": list(self._referenced_skill_ids),
        }


def repository_revision(workspace: Path) -> str | None:
    """读取当前 Git HEAD；非仓库、超时或非完整 SHA 时返回 unknown。"""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        completed = subprocess.run(
            (git, "-C", str(workspace), "rev-parse", "HEAD"),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = completed.stdout.strip()
    valid = completed.returncode == 0 and len(revision) in {40, 64} and all(c in "0123456789abcdef" for c in revision)
    return revision if valid else None


def verification_name(command: str) -> str | None:
    """仅识别冻结的测试、构建和静态检查命令，不从输出文本猜测 Verification。"""
    if any(operator in command for operator in ("&&", "||", ";", "|", "&", "\n", "\r")):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    if not tokens:
        return None
    executable = PurePath(tokens[0]).name
    accepted = False
    if executable in {"pytest", "mypy", "tox", "nox"}:
        accepted = True
    elif executable == "ruff":
        accepted = len(tokens) > 1 and tokens[1] in {"check", "format"}
    elif executable == "make":
        accepted = any(target in {"check", "ci", "lint", "test"} for target in tokens[1:])
    elif executable in {"npm", "pnpm", "yarn", "bun"}:
        accepted = len(tokens) > 1 and (
            tokens[1] == "test" or (tokens[1] == "run" and len(tokens) > 2 and tokens[2] in {"build", "test"})
        )
    elif executable == "cargo":
        accepted = len(tokens) > 1 and tokens[1] in {"build", "check", "test"}
    elif executable == "go":
        accepted = len(tokens) > 1 and tokens[1] in {"build", "test", "vet"}
    elif executable in {"gradle", "gradlew", "mvn", "mvnw"}:
        accepted = True
    return executable if accepted else None


def _relative_path(value: object, *, workspace: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        path = Path(value)
        resolved = (workspace / path).resolve() if not path.is_absolute() else path.resolve()
        return resolved.relative_to(workspace).as_posix()
    except (OSError, ValueError):
        return None


__all__ = ["TurnEvidenceLog", "repository_revision", "verification_name"]
