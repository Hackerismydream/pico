from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from benchmarks.picobench.verifier import (
    JsonArtifactVerifier,
    VerifierExecution,
    VerifierSeal,
    run_sealed_verifier,
)

from .models import ContextTask


@dataclass(frozen=True)
class SealedContextTaskVerifier:
    task: ContextTask
    expected_path: Path
    seal: VerifierSeal

    @classmethod
    def capture(
        cls,
        task: ContextTask,
        *,
        expected_path: Path | None = None,
    ) -> "SealedContextTaskVerifier":
        resolved = Path(expected_path or task.expected_path)
        return cls(
            task=task,
            expected_path=resolved,
            seal=VerifierSeal.capture(resolved),
        )

    async def verify(self, workspace: Path) -> VerifierExecution:
        verifier = JsonArtifactVerifier(
            expected_path=self.expected_path,
            artifact_path=self.task.artifact_path,
            forbidden_paths=self.task.forbidden_paths,
        )
        return await run_sealed_verifier(
            verifier,
            workspace=workspace,
            seal=self.seal,
        )


__all__ = ["SealedContextTaskVerifier"]
