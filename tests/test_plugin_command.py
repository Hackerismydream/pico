"""``pico plugins`` reports the installed CodeCairn Plugin without starting it."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from typer.testing import CliRunner


def _make_runner_args(tmp_path: Path, config: dict[str, Any]) -> list[str]:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return ["plugins", "-c", str(config_path)]


def _invoke(args: list[str], tmp_path: Path):
    from pico.cli.commands import app

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(fake_home), "COLUMNS": "200"}
    return CliRunner().invoke(app, args, env=env)


def test_lists_installed_codecairn_plugin(tmp_path: Path) -> None:
    result = _invoke(_make_runner_args(tmp_path, {}), tmp_path)

    assert result.exit_code == 0, result.stdout
    assert "codecairn-memory" in result.stdout
    assert "0.1.0" in result.stdout
    assert "entry_points" in result.stdout


def test_shows_active_codecairn_backend(tmp_path: Path) -> None:
    result = _invoke(
        _make_runner_args(
            tmp_path,
            {"memory": {"backend": "codecairn", "userId": "alice"}},
        ),
        tmp_path,
    )

    assert result.exit_code == 0, result.stdout
    assert "Active memory backend" in result.stdout
    assert "codecairn" in result.stdout
    assert "from plugin: codecairn-memory" in result.stdout
    assert "User id:" in result.stdout
    assert "alice" in result.stdout
    assert "Agent id:" not in result.stdout


def test_null_backend_reports_memory_disabled(tmp_path: Path) -> None:
    result = _invoke(
        _make_runner_args(tmp_path, {"memory": {"backend": None}}),
        tmp_path,
    )

    assert result.exit_code == 0, result.stdout
    assert "Active memory backend" in result.stdout
    assert "none" in result.stdout
    assert "Memory is disabled" in result.stdout
    assert "legacy" not in result.stdout


def test_unknown_backend_is_fail_closed(tmp_path: Path) -> None:
    result = _invoke(
        _make_runner_args(tmp_path, {"memory": {"backend": "nonexistent"}}),
        tmp_path,
    )

    assert result.exit_code == 0, result.stdout
    assert "nonexistent" in result.stdout
    assert "not available" in result.stdout
    assert "fail closed" in result.stdout
    assert "fall back" not in result.stdout


def test_disabled_codecairn_plugin_status(tmp_path: Path) -> None:
    result = _invoke(
        _make_runner_args(
            tmp_path,
            {"plugins": {"disabled": ["codecairn-memory"]}},
        ),
        tmp_path,
    )

    assert result.exit_code == 0, result.stdout
    assert "codecairn-memory" in result.stdout
    assert "disabled" in result.stdout
    assert "not available" in result.stdout


def test_verbose_shows_codecairn_factory(tmp_path: Path) -> None:
    args = _make_runner_args(tmp_path, {})
    args.append("--verbose")

    result = _invoke(args, tmp_path)

    assert result.exit_code == 0, result.stdout
    assert "codecairn.integrations.pico.backend:make_backend" in result.stdout
