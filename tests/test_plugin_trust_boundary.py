"""Security contracts for plugin discovery and import timing."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from pico.cli._plugin_stack import plugin_discovery_sources
from pico.plugin import PluginDiscovery, ServiceLocator, assemble_plugin_registry


@pytest.fixture(autouse=True)
def _restore_import_state():
    path_snapshot = list(sys.path)
    modules_snapshot = set(sys.modules)
    yield
    sys.path[:] = path_snapshot
    for name in set(sys.modules) - modules_snapshot:
        if name.startswith("trust_boundary_plugin"):
            sys.modules.pop(name, None)


def _write_tool_plugin(root: Path, *, marker: Path) -> Path:
    plugin_dir = root / "trust-boundary"
    package = plugin_dir / "trust_boundary_plugin"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "factories.py").write_text(
        textwrap.dedent(
            f"""
            from pathlib import Path

            Path({str(marker)!r}).write_text("imported", encoding="utf-8")

            def make_tool(ctx):
                return {{"workspace": str(ctx.services.workspace)}}
            """
        ),
        encoding="utf-8",
    )
    (plugin_dir / "pico-plugin.toml").write_text(
        textwrap.dedent(
            """
            [plugin]
            id = "trust-boundary"
            version = "0.1.0"
            enabled_by_default = true

            [[plugin.contributes.tools]]
            name = "trust_boundary_tool"
            factory = "trust_boundary_plugin.factories:make_tool"
            """
        ),
        encoding="utf-8",
    )
    return plugin_dir


def test_repository_local_plugins_are_not_an_automatic_host_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    repo_plugins = checkout / ".pico" / "plugins"
    marker = tmp_path / "repo-imported"
    _write_tool_plugin(repo_plugins, marker=marker)
    monkeypatch.chdir(checkout)

    sources = plugin_discovery_sources()

    assert sources["project_dir"] is None
    assert (
        PluginDiscovery(
            project_dir=sources["project_dir"],
            entry_points_group=None,
        ).discover()
        == []
    )
    assert not marker.exists()


def test_manifest_activation_defers_user_plugin_import_until_build(
    tmp_path: Path,
) -> None:
    user_plugins = tmp_path / "user-plugins"
    marker = tmp_path / "user-imported"
    plugin_dir = _write_tool_plugin(user_plugins, marker=marker)

    registry = assemble_plugin_registry(
        user_dir=user_plugins,
        entry_points_group=None,
    )

    assert registry.activated_ids() == ["trust-boundary"]
    assert registry.tool_names() == ["trust_boundary_tool"]
    assert str(plugin_dir) not in sys.path
    assert not marker.exists()

    tool = registry.build_tool(
        "trust_boundary_tool",
        config={},
        services=ServiceLocator(workspace=tmp_path),
    )

    assert tool == {"workspace": str(tmp_path)}
    assert str(plugin_dir) in sys.path
    assert marker.read_text(encoding="utf-8") == "imported"
