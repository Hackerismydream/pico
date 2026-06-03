from pathlib import Path
from artifact_locator import locate_artifacts


def test_relative_evidence_paths_are_resolved(tmp_path):
    assert locate_artifacts(tmp_path, {'evidence_paths': ['evidence/core_001-run1']}) == [str(tmp_path / 'evidence/core_001-run1')]
