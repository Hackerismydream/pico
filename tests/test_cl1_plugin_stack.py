"""Installed plugin-stack assembly and retired backend errors."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from pico.cli._plugin_stack import MynaSetupError, maybe_build_memory_backend
from pico.config.pico import MemoryConfig, PicoConfig, PluginsConfig
from pico.memory_engine import MemoryBackend
from pico.plugin import (
    Contributes,
    DiscoveredPlugin,
    MemoryBackendContribution,
    PluginIdentityError,
    PluginManifest,
    PluginNotFoundError,
    PluginRegistry,
    Source,
)


def _config(memory_backend: str | None = "myna") -> PicoConfig:
    return PicoConfig(
        memory=MemoryConfig(backend=memory_backend),
        plugins=PluginsConfig(),
    )


def _registry(
    *,
    plugin_id: str = "myna-memory",
    factory_ref: str = "myna.integrations.pico.backend:make_backend",
    start_error: Exception | None = None,
):
    module_name = factory_ref.partition(":")[0]
    module = types.ModuleType(module_name)

    class Backend:
        async def recall(self, query, *, user_id=None, agent_id=None, top_k=5):
            return []

        async def store(self, session_id, messages):
            return None

        async def feedback(self, signals):
            return None

        async def start(self):
            if start_error is not None:
                raise start_error
            return None

        async def stop(self):
            return None

    module.make_backend = lambda _context: Backend()
    sys.modules[module_name] = module
    registry = PluginRegistry()
    registry.activate(
        [
            DiscoveredPlugin(
                manifest=PluginManifest(
                    id=plugin_id,
                    version="0.1.1rc3",
                    pico=">=0.1,<0.2",
                    enabled_by_default=True,
                    contributes=Contributes(
                        memory_backends=[MemoryBackendContribution(name="myna", factory=factory_ref)]
                    ),
                ),
                source=Source.ENTRY_POINTS,
                location=None,
            )
        ]
    )
    return registry


def test_default_config_builds_validated_myna_backend(tmp_path: Path) -> None:
    backend = maybe_build_memory_backend(tmp_path, _config(), registry=_registry())
    assert isinstance(backend, MemoryBackend)


def test_memory_backend_none_returns_none(tmp_path: Path) -> None:
    assert maybe_build_memory_backend(tmp_path, _config(None)) is None


async def test_myna_uninitialized_error_has_setup_remediation(tmp_path: Path) -> None:
    class ConfigurationInvalid(RuntimeError):
        code = "configuration_invalid"

    backend = maybe_build_memory_backend(
        tmp_path,
        _config(),
        registry=_registry(start_error=ConfigurationInvalid("invalid")),
    )
    assert backend is not None

    with pytest.raises(MynaSetupError, match=r"myna init.*myna doctor --live"):
        await backend.start()


def test_unknown_backend_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginNotFoundError):
        maybe_build_memory_backend(tmp_path, _config("nonexistent"))


@pytest.mark.parametrize("retired", ["codecairn", "everos"])
def test_retired_backend_fails_without_rewrite(
    tmp_path: Path,
    retired: str,
) -> None:
    config_path = tmp_path / "config.json"
    data = {"memory": {"backend": retired}}
    config_path.write_text(json.dumps(data), encoding="utf-8")
    config = _config(retired)

    with pytest.raises(
        PluginNotFoundError,
        match="set memory.backend to 'myna'.*or set it to null",
    ):
        maybe_build_memory_backend(tmp_path, config)

    assert json.loads(config_path.read_text(encoding="utf-8")) == data


@pytest.mark.parametrize(
    ("plugin_id", "factory_ref"),
    [
        ("other-memory", "_test_myna_backend:make_backend"),
        ("myna-memory", "other.module:make_backend"),
    ],
)
def test_myna_backend_requires_frozen_public_manifest_identity(
    tmp_path: Path,
    plugin_id: str,
    factory_ref: str,
) -> None:
    registry = _registry(plugin_id=plugin_id, factory_ref=factory_ref)

    with pytest.raises(PluginIdentityError, match="Myna plugin manifest identity"):
        maybe_build_memory_backend(tmp_path, _config(), registry=registry)
