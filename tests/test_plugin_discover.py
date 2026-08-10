"""PG-2 — multi-source plugin discovery + conflict resolution."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from pico.plugin import (
    DiscoveredPlugin,
    PluginDiscovery,
    Source,
)


def _write_manifest(root: Path, plugin_id: str, *, extra: str = "") -> Path:
    """Drop a minimal valid manifest at ``root/<plugin_id>/pico-plugin.toml``."""
    sub = root / plugin_id
    sub.mkdir(parents=True, exist_ok=True)
    body = textwrap.dedent(
        f"""
        [plugin]
        id = "{plugin_id}"
        version = "0.1.0"
        {extra}
        """
    )
    path = sub / "pico-plugin.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# File-based scanning
# ---------------------------------------------------------------------------


class TestSingleSource:
    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        d = PluginDiscovery(bundled_dir=tmp_path)
        assert d.discover() == []

    def test_nonexistent_dir_returns_empty_list(self, tmp_path: Path) -> None:
        d = PluginDiscovery(bundled_dir=tmp_path / "missing")
        assert d.discover() == []

    def test_finds_single_manifest(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "foo")
        d = PluginDiscovery(bundled_dir=tmp_path)
        out = d.discover()
        assert len(out) == 1
        assert out[0].manifest.id == "foo"
        assert out[0].source == Source.BUNDLED
        assert out[0].location is not None
        assert out[0].location.name == "pico-plugin.toml"

    def test_finds_multiple_manifests_sorted_by_id(self, tmp_path: Path) -> None:
        for pid in ("zeta", "alpha", "mid"):
            _write_manifest(tmp_path, pid)
        d = PluginDiscovery(user_dir=tmp_path)
        ids = [p.manifest.id for p in d.discover()]
        assert ids == ["alpha", "mid", "zeta"]

    def test_subdir_without_manifest_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "not-a-plugin").mkdir()
        _write_manifest(tmp_path, "real")
        d = PluginDiscovery(bundled_dir=tmp_path)
        assert [p.manifest.id for p in d.discover()] == ["real"]

    def test_malformed_manifest_skipped_silently(
        self,
        tmp_path: Path,
        caplog,
    ) -> None:
        sub = tmp_path / "broken"
        sub.mkdir()
        (sub / "pico-plugin.toml").write_text(
            "not valid toml [[[",
            encoding="utf-8",
        )
        _write_manifest(tmp_path, "ok")
        d = PluginDiscovery(bundled_dir=tmp_path)
        out = d.discover()
        # Broken one is skipped; valid one returned.
        assert [p.manifest.id for p in out] == ["ok"]


# ---------------------------------------------------------------------------
# Installed entry-point scanning
# ---------------------------------------------------------------------------


class _FakeDistribution:
    def __init__(self, root: Path, relative_manifest: PurePosixPath) -> None:
        self._root = root
        self.files = [relative_manifest]

    def locate_file(self, relative_path) -> Path:
        return self._root / Path(str(relative_path))


class TestEntryPointSource:
    def test_reads_distribution_manifest_without_importing_package(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        package = tmp_path / "entry_plugin"
        package.mkdir()
        marker = tmp_path / "package-imported"
        (package / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported', encoding='utf-8')\n",
            encoding="utf-8",
        )
        (package / "pico-plugin.toml").write_text(
            textwrap.dedent(
                """
                [plugin]
                id = "entry-plugin"
                version = "0.1.0"
                enabled_by_default = true

                [[plugin.contributes.tools]]
                name = "entry_tool"
                factory = "entry_plugin:make_tool"
                """
            ),
            encoding="utf-8",
        )
        relative_manifest = PurePosixPath(
            "entry_plugin",
            "pico-plugin.toml",
        )
        entry_point = SimpleNamespace(
            name="entry-plugin",
            value="entry_plugin",
            module="entry_plugin",
            dist=_FakeDistribution(tmp_path, relative_manifest),
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(
            "pico.plugin.discover.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        sys.modules.pop("entry_plugin", None)

        discovered = PluginDiscovery(
            entry_points_group="pico.plugins",
        ).discover()

        assert [item.manifest.id for item in discovered] == ["entry-plugin"]
        assert discovered[0].source is Source.ENTRY_POINTS
        assert discovered[0].location is None
        assert "entry_plugin" not in sys.modules
        assert not marker.exists()

    def test_unrecorded_manifest_is_skipped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog,
    ) -> None:
        entry_point = SimpleNamespace(
            name="missing-manifest",
            value="missing_plugin",
            module="missing_plugin",
            dist=_FakeDistribution(
                tmp_path,
                PurePosixPath("other", "pico-plugin.toml"),
            ),
        )
        monkeypatch.setattr(
            "pico.plugin.discover.metadata.entry_points",
            lambda *, group: [entry_point],
        )

        assert (
            PluginDiscovery(
                entry_points_group="pico.plugins",
            ).discover()
            == []
        )
        assert "does not record pico-plugin.toml" in caplog.text


# ---------------------------------------------------------------------------
# Cross-source conflict resolution
# ---------------------------------------------------------------------------


class TestConflictResolution:
    def test_bundled_shadows_user(self, tmp_path: Path, caplog) -> None:
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        _write_manifest(bundled, "example")
        _write_manifest(user, "example")
        d = PluginDiscovery(bundled_dir=bundled, user_dir=user)
        out = d.discover()
        assert len(out) == 1
        # Bundled wins per the "builtin shadow rule".
        assert out[0].source == Source.BUNDLED

    def test_user_shadows_project(self, tmp_path: Path) -> None:
        user = tmp_path / "user"
        project = tmp_path / "project"
        _write_manifest(user, "myplug")
        _write_manifest(project, "myplug")
        d = PluginDiscovery(user_dir=user, project_dir=project)
        out = d.discover()
        assert len(out) == 1
        assert out[0].source == Source.USER

    def test_priority_order_full_chain(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        project = tmp_path / "project"
        # Same id across three sources — bundled must win.
        _write_manifest(bundled, "x")
        _write_manifest(user, "x")
        _write_manifest(project, "x")
        # Add unique ones at each level to confirm non-conflicting
        # plugins all surface.
        _write_manifest(bundled, "b-only")
        _write_manifest(user, "u-only")
        _write_manifest(project, "p-only")
        d = PluginDiscovery(
            bundled_dir=bundled,
            user_dir=user,
            project_dir=project,
        )
        out = d.discover()
        by_id = {p.manifest.id: p.source for p in out}
        assert by_id == {
            "b-only": Source.BUNDLED,
            "u-only": Source.USER,
            "p-only": Source.PROJECT,
            "x": Source.BUNDLED,
        }


# ---------------------------------------------------------------------------
# Subdir-name vs manifest-id mismatch
# ---------------------------------------------------------------------------


class TestSubdirNameMismatch:
    def test_id_in_manifest_wins(self, tmp_path: Path) -> None:
        # Directory called "wrong-dirname" but manifest declares id "correct"
        sub = tmp_path / "wrong-dirname"
        sub.mkdir()
        (sub / "pico-plugin.toml").write_text(
            textwrap.dedent(
                """
                [plugin]
                id = "correct"
                version = "0.1"
                """
            ),
            encoding="utf-8",
        )
        d = PluginDiscovery(bundled_dir=tmp_path)
        out = d.discover()
        assert out[0].manifest.id == "correct"


# ---------------------------------------------------------------------------
# Frozen record sanity
# ---------------------------------------------------------------------------


class TestDiscoveredPluginRecord:
    def test_record_is_frozen(self, tmp_path: Path) -> None:
        from dataclasses import FrozenInstanceError

        _write_manifest(tmp_path, "x")
        out = PluginDiscovery(bundled_dir=tmp_path).discover()
        rec: DiscoveredPlugin = out[0]
        with pytest.raises(FrozenInstanceError):
            rec.source = Source.USER  # type: ignore[misc]
