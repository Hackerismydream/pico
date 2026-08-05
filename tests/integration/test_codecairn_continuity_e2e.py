from __future__ import annotations

import os
from pathlib import Path

import pytest

from benchmarks.picobench.codecairn_continuity import run_continuity_gate


@pytest.mark.external_runtime
def test_installed_codecairn_continuity_gate(tmp_path: Path) -> None:
    names = (
        "PICO_CODECAIRN_PICO_WHEEL",
        "PICO_CODECAIRN_WHEEL",
        "PICO_CODECAIRN_PICO_HANDOFF",
        "PICO_CODECAIRN_HANDOFF",
        "PICO_CODECAIRN_IMPLEMENTATION_PICO_WHEEL",
        "PICO_CODECAIRN_COMPATIBILITY_PICO_WHEEL",
        "PICO_CODECAIRN_PICO_DISTRIBUTION_REPORT",
        "PICO_CODECAIRN_COMMIT",
        "PICO_CODECAIRN_SOURCE_ROOT",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip("installed continuity inputs are not configured")

    result = run_continuity_gate(
        pico_wheel=Path(os.environ["PICO_CODECAIRN_PICO_WHEEL"]),
        codecairn_wheel=Path(os.environ["PICO_CODECAIRN_WHEEL"]),
        pico_handoff=Path(os.environ["PICO_CODECAIRN_PICO_HANDOFF"]),
        codecairn_handoff=Path(os.environ["PICO_CODECAIRN_HANDOFF"]),
        pico_implementation_wheel=Path(os.environ["PICO_CODECAIRN_IMPLEMENTATION_PICO_WHEEL"]),
        pico_compatibility_wheel=Path(os.environ["PICO_CODECAIRN_COMPATIBILITY_PICO_WHEEL"]),
        pico_distribution_report=Path(os.environ["PICO_CODECAIRN_PICO_DISTRIBUTION_REPORT"]),
        pico_commit=os.environ["PICO_CODECAIRN_COMMIT"],
        pico_source_root=Path.cwd(),
        codecairn_source_root=Path(os.environ["PICO_CODECAIRN_SOURCE_ROOT"]),
        output_root=tmp_path / "evidence",
    )

    assert result.pair_manifest.exists()
    assert result.summary.exists()
