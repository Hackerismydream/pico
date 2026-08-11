"""Contract checks for the public Pico installers."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["install.sh", "install.ps1"])
def test_installer_uses_current_repository_and_pairs_myna(name: str) -> None:
    source = (ROOT / name).read_text(encoding="utf-8")

    assert "Hackerismydream/pico/releases/latest" in source
    assert "Hackerismydream/pico-harness" not in source
    assert "MYNA_WHEEL_URL" in source
    assert "--with-executables-from" in source
    assert "pico onboard" in source
