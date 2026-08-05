from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from benchmarks.picobench.canonical import canonical_digest, to_primitive
from benchmarks.picobench.records import (
    VerificationState,
    VerifierResult,
)
from benchmarks.picobench.verifier import (
    VerifierExecution,
    require_normalized_relative_path,
)

from .fixtures import (
    expected_repository_paths,
    fixture_file_drift,
    observed_repository_paths,
)
from .models import (
    TaskEffectTask,
    TaskEffectTestState,
    TaskEffectVerificationEvidence,
)


def task_effect_verifier_code_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class SealedTaskEffectVerifier:
    task: TaskEffectTask
    expected_data_digest: str
    verifier_code_digest: str

    @classmethod
    def capture(
        cls,
        task: TaskEffectTask,
    ) -> SealedTaskEffectVerifier:
        return cls(
            task=task,
            expected_data_digest=_expected_data_digest(task),
            verifier_code_digest=task_effect_verifier_code_digest(),
        )

    async def verify(
        self,
        workspace: Path,
        evidence: TaskEffectVerificationEvidence,
    ) -> VerifierExecution:
        if self.expected_data_digest != _expected_data_digest(self.task):
            return _infrastructure_failure("task_effect_expected_data_changed")
        if self.verifier_code_digest != task_effect_verifier_code_digest():
            return _infrastructure_failure("task_effect_verifier_code_changed")

        workspace = Path(workspace)
        if workspace.is_symlink():
            return VerifierExecution(
                result=VerifierResult(
                    state=VerificationState.FAILED,
                    findings=("workspace_symlink",),
                )
            )
        workspace = workspace.resolve()
        if not workspace.is_dir():
            return VerifierExecution(
                result=VerifierResult(
                    state=VerificationState.FAILED,
                    findings=("workspace_missing",),
                )
            )
        findings = [
            *fixture_file_drift(self.task.fixture, workspace),
            *self._path_policy_findings(workspace, evidence),
            *self._artifact_findings(workspace),
            *self._receipt_findings(evidence),
            *self._test_state_findings(evidence.test_state),
        ]
        if self.expected_data_digest != _expected_data_digest(self.task):
            return _infrastructure_failure("task_effect_expected_data_changed")
        if self.verifier_code_digest != task_effect_verifier_code_digest():
            return _infrastructure_failure("task_effect_verifier_code_changed")
        if findings:
            return VerifierExecution(
                result=VerifierResult(
                    state=VerificationState.FAILED,
                    findings=tuple(dict.fromkeys(findings)),
                    metrics={
                        "required_receipt_count": len(self.task.required_receipt_ids),
                        "observed_receipt_count": len(evidence.receipt_ids),
                    },
                )
            )
        return VerifierExecution(
            result=VerifierResult(
                state=VerificationState.PASSED,
                metrics={
                    "required_receipt_count": len(self.task.required_receipt_ids),
                    "observed_receipt_count": len(evidence.receipt_ids),
                    "path_policy_passed": True,
                    "test_state_passed": True,
                },
            )
        )

    def _path_policy_findings(
        self,
        workspace: Path,
        evidence: TaskEffectVerificationEvidence,
    ) -> tuple[str, ...]:
        findings: list[str] = []
        expected_paths = set(expected_repository_paths(self.task.fixture))
        observed_paths = set(observed_repository_paths(workspace))
        allowed_paths = set(self.task.allowed_mutation_paths)
        unexpected_paths = observed_paths - expected_paths - allowed_paths
        findings.extend(f"path_policy_unexpected:{path}" for path in sorted(unexpected_paths))
        for path in self.task.forbidden_paths:
            resolved = _workspace_path(workspace, path)
            if resolved is None:
                findings.append(f"forbidden_path_outside_workspace:{path}")
            elif resolved.exists():
                findings.append(f"forbidden_path:{path}")

        normalized_changed: list[str] = []
        for path in evidence.changed_paths:
            try:
                normalized_changed.append(
                    require_normalized_relative_path(
                        path,
                        field_name="changed_paths",
                    )
                )
            except ValueError:
                findings.append(f"changed_path_invalid:{path}")
        changed_set = set(normalized_changed)
        findings.extend(f"path_policy_changed:{path}" for path in sorted(changed_set - allowed_paths))
        if self.task.artifact_path not in changed_set:
            findings.append("artifact_change_receipt_missing")
        if len(normalized_changed) != len(set(normalized_changed)):
            findings.append("duplicate_changed_path")
        return tuple(findings)

    def _artifact_findings(
        self,
        workspace: Path,
    ) -> tuple[str, ...]:
        artifact = _workspace_path(workspace, self.task.artifact_path)
        if artifact is None:
            return (f"artifact_path_outside_workspace:{self.task.artifact_path}",)
        if artifact.is_symlink():
            return ("artifact_symlink",)
        if not artifact.is_file():
            return (f"missing_artifact:{self.task.artifact_path}",)
        try:
            actual = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return (f"invalid_artifact_json:{type(exc).__name__}",)
        if actual != to_primitive(self.task.expected_artifact.payload):
            return ("artifact_mismatch",)
        return ()

    def _receipt_findings(
        self,
        evidence: TaskEffectVerificationEvidence,
    ) -> tuple[str, ...]:
        observed = set(evidence.receipt_ids)
        missing = set(self.task.required_receipt_ids) - observed
        findings = [f"required_receipt_missing:{receipt_id}" for receipt_id in sorted(missing)]
        if len(evidence.receipt_ids) != len(observed):
            findings.append("duplicate_receipt_id")
        return tuple(findings)

    def _test_state_findings(
        self,
        test_state: TaskEffectTestState | None,
    ) -> tuple[str, ...]:
        if test_state is None:
            return ("test_state_missing",)
        findings: list[str] = []
        if test_state.command != self.task.test_command:
            findings.append("test_command_mismatch")
        if test_state.exit_code != 0:
            findings.append(f"test_state_failed:{test_state.exit_code}")
        if test_state.fixture_digest != self.task.fixture.digest:
            findings.append("test_fixture_digest_mismatch")
        return tuple(findings)


def valid_verification_evidence(
    task: TaskEffectTask,
) -> TaskEffectVerificationEvidence:
    return TaskEffectVerificationEvidence(
        receipt_ids=task.required_receipt_ids,
        changed_paths=(task.artifact_path,),
        test_state=TaskEffectTestState(
            command=task.test_command,
            exit_code=0,
            fixture_digest=task.fixture.digest,
        ),
    )


def _expected_data_digest(task: TaskEffectTask) -> str:
    return canonical_digest(
        {
            "task_id": task.task_id,
            "fixture_digest": task.fixture.digest,
            "expected_id": task.expected_id,
            "expected_digest": task.expected_digest,
            "artifact_path": task.artifact_path,
            "allowed_mutation_paths": task.allowed_mutation_paths,
            "forbidden_paths": task.forbidden_paths,
            "required_receipt_ids": task.required_receipt_ids,
            "test_command": task.test_command,
            "parent_owned_mutation": task.mutation_contract,
        }
    )


def _workspace_path(
    workspace: Path,
    relative: str,
) -> Path | None:
    candidate = workspace.joinpath(*PurePosixPath(relative).parts).resolve()
    if not candidate.is_relative_to(workspace):
        return None
    return candidate


def _infrastructure_failure(reason: str) -> VerifierExecution:
    return VerifierExecution(
        result=VerifierResult(state=VerificationState.NOT_RUN),
        infrastructure_error=reason,
    )


__all__ = [
    "SealedTaskEffectVerifier",
    "task_effect_verifier_code_digest",
    "valid_verification_evidence",
]
