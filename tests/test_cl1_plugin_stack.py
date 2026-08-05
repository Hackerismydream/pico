"""Installed plugin-stack assembly and legacy backend migration errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pico.cli._plugin_stack import build_plugin_registry, maybe_build_memory_backend
from pico.config.pico import MemoryConfig, PicoConfig, PluginsConfig
from pico.memory_engine import MemoryBackend
from pico.plugin import PluginNotFoundError, PluginRegistry


def _config(memory_backend: str | None = "codecairn") -> PicoConfig:
    return PicoConfig(
        memory=MemoryConfig(backend=memory_backend),
        plugins=PluginsConfig(),
    )


def test_registry_discovers_installed_codecairn_plugin() -> None:
    registry = build_plugin_registry(_config())
    assert isinstance(registry, PluginRegistry)
    assert "codecairn-memory" in registry.activated_ids()
    assert "codecairn" in registry.memory_backend_names()


def test_default_config_builds_installed_codecairn_backend(tmp_path: Path) -> None:
    backend = maybe_build_memory_backend(tmp_path, _config())
    assert isinstance(backend, MemoryBackend)


def test_memory_backend_none_returns_none(tmp_path: Path) -> None:
    assert maybe_build_memory_backend(tmp_path, _config(None)) is None


def test_unknown_backend_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginNotFoundError):
        maybe_build_memory_backend(tmp_path, _config("nonexistent"))


def test_legacy_backend_fails_with_actionable_migration_without_rewrite(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    data = {"memory": {"backend": "everos"}}
    config_path.write_text(json.dumps(data), encoding="utf-8")
    config = _config("everos")

    with pytest.raises(
        PluginNotFoundError,
        match="set memory.backend to 'codecairn'.*or set it to null",
    ):
        maybe_build_memory_backend(tmp_path, config)

    assert json.loads(config_path.read_text(encoding="utf-8")) == data
