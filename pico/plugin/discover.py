"""Multi-source plugin discovery.

A discovery pass scans every source the host knows about (bundled
sub-tree, user-level dir, project-level dir, pip entry points),
deduplicates by plugin id, and returns a stable list of
:class:`DiscoveredPlugin` records. Discovery only reads manifests — no
plugin Python code is imported here. The :class:`Source` enum doubles
as the conflict-resolution priority ordering (higher wins).

Priority order (`bundled > user > project > entry_points`) follows the
design's "builtin shadow rule": a bundled plugin can never be shadowed
by a same-named local or pip-installed one. Among the non-bundled
sources, user-level wins so a developer can substitute a locally edited
copy for a pip-installed version while iterating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from pico.plugin.manifest import PluginManifest

logger = logging.getLogger(__name__)


_MANIFEST_FILENAME = "pico-plugin.toml"


class Source(IntEnum):
    """Where a manifest came from. Numeric value is conflict priority —
    higher wins. Lower values lose silently and are logged."""

    ENTRY_POINTS = 1
    PROJECT = 2
    USER = 3
    BUNDLED = 4


@dataclass(frozen=True)
class DiscoveredPlugin:
    """A manifest read from a specific source, awaiting activation."""

    manifest: PluginManifest
    source: Source
    location: Path | None
    """Path to the manifest file. ``None`` for entry-points-discovered
    plugins whose factories resolve through the installed distribution."""


class PluginDiscovery:
    """Scans every configured source and returns deduplicated plugins.

    Constructor params default to "off"; callers pass concrete paths
    or the entry-point group name to opt each source in. This keeps
    tests hermetic — they construct a discovery instance pointing at
    tmp dirs and don't accidentally pick up real plugins on the
    developer's machine.
    """

    def __init__(
        self,
        *,
        bundled_dir: Path | None = None,
        user_dir: Path | None = None,
        project_dir: Path | None = None,
        entry_points_group: str | None = None,
    ) -> None:
        self._bundled_dir = bundled_dir
        self._user_dir = user_dir
        self._project_dir = project_dir
        self._entry_points_group = entry_points_group

    def discover(self) -> list[DiscoveredPlugin]:
        """Run all enabled sources and resolve conflicts.

        The returned list is stable-ordered by plugin id so callers can
        log / display it deterministically.
        """
        all_found: list[DiscoveredPlugin] = []
        if self._bundled_dir is not None:
            all_found.extend(
                self._scan_dir(self._bundled_dir, Source.BUNDLED),
            )
        if self._user_dir is not None:
            all_found.extend(self._scan_dir(self._user_dir, Source.USER))
        if self._project_dir is not None:
            all_found.extend(
                self._scan_dir(self._project_dir, Source.PROJECT),
            )
        if self._entry_points_group is not None:
            all_found.extend(self._scan_entry_points(self._entry_points_group))

        return self._resolve_conflicts(all_found)

    # ── File-based sources ─────────────────────────────────────────

    def _scan_dir(
        self,
        root: Path,
        source: Source,
    ) -> list[DiscoveredPlugin]:
        """Look for ``<root>/<plugin_id>/pico-plugin.toml``.

        Subdir name is informational only — the canonical plugin id is
        the one inside the manifest. A mismatch is logged but the
        manifest still loads.
        """
        out: list[DiscoveredPlugin] = []
        if not root.is_dir():
            return out
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            manifest_path = sub / _MANIFEST_FILENAME
            if not manifest_path.is_file():
                continue
            try:
                mf = PluginManifest.from_toml_path(manifest_path)
            except Exception as e:
                logger.warning(
                    "plugin manifest %s failed to parse (%s); skipping",
                    manifest_path,
                    e,
                )
                continue
            if mf.id != sub.name:
                logger.info(
                    "plugin %s lives in directory %s — id and dir name differ",
                    mf.id,
                    sub.name,
                )
            out.append(
                DiscoveredPlugin(
                    manifest=mf,
                    source=source,
                    location=manifest_path,
                ),
            )
        return out

    # ── Entry-points source ────────────────────────────────────────

    def _scan_entry_points(self, group: str) -> list[DiscoveredPlugin]:
        """Read installed plugin manifests without importing their packages.

        Entry-point values name the package that ships ``pico-plugin.toml``.
        The manifest is resolved from the owning distribution's recorded file
        inventory instead of through ``importlib.resources``. This keeps
        discovery data-only: package ``__init__`` code and native dependencies
        are not loaded until the Registry actually resolves a selected factory.

        A distribution that omits its manifest from package metadata is
        skipped rather than imported as a fallback.
        """
        out: list[DiscoveredPlugin] = []
        try:
            eps = metadata.entry_points(group=group)
        except Exception as e:
            logger.warning("entry_points discovery failed (%s); skipping", e)
            return out

        for ep in eps:
            package_name = _entry_point_package_name(ep)
            try:
                manifest_path = _entry_point_manifest_path(
                    ep,
                    package_name=package_name,
                )
                if manifest_path is None:
                    logger.warning(
                        "entry-point %s points at package %s but its distribution does not record %s; skipping",
                        ep.name,
                        package_name,
                        _MANIFEST_FILENAME,
                    )
                    continue
                mf = PluginManifest.from_toml_path(manifest_path)
                out.append(
                    DiscoveredPlugin(
                        manifest=mf,
                        source=Source.ENTRY_POINTS,
                        location=None,
                    ),
                )
            except Exception as e:
                logger.warning(
                    "failed to load manifest for entry-point %s (%s); skipping",
                    ep.name,
                    e,
                )
        return out

    # ── Conflict resolution ────────────────────────────────────────

    @staticmethod
    def _resolve_conflicts(
        found: list[DiscoveredPlugin],
    ) -> list[DiscoveredPlugin]:
        """Group by plugin id, keep the highest-priority source.

        Lower-priority duplicates are logged once each so a misconfigured
        setup is debuggable without silently dropping plugins.
        """
        by_id: dict[str, DiscoveredPlugin] = {}
        for d in found:
            current = by_id.get(d.manifest.id)
            if current is None or d.source > current.source:
                if current is not None:
                    logger.info(
                        "plugin %s: %s shadows %s",
                        d.manifest.id,
                        d.source.name,
                        current.source.name,
                    )
                by_id[d.manifest.id] = d
            elif d.source < current.source:
                logger.info(
                    "plugin %s: %s shadowed by %s",
                    d.manifest.id,
                    d.source.name,
                    current.source.name,
                )
        # Stable sort by id so caller-side display order is deterministic.
        return sorted(by_id.values(), key=lambda p: p.manifest.id)


def _entry_point_package_name(entry_point: Any) -> str:
    module = getattr(entry_point, "module", None)
    if isinstance(module, str) and module:
        return module
    return str(entry_point.value).split(":", 1)[0]


def _entry_point_manifest_path(
    entry_point: Any,
    *,
    package_name: str,
) -> Path | None:
    distribution = getattr(entry_point, "dist", None)
    if distribution is None:
        return None
    distribution_files = getattr(distribution, "files", None)
    if not distribution_files:
        return None

    target = PurePosixPath(*package_name.split("."), _MANIFEST_FILENAME)
    match = None
    for candidate in distribution_files:
        normalized = PurePosixPath(str(candidate).replace("\\", "/"))
        if normalized == target:
            if match is not None:
                raise ValueError(
                    f"distribution records {target} more than once",
                )
            match = candidate
    if match is None:
        return None

    located = distribution.locate_file(match)
    manifest_path = Path(located)
    return manifest_path if manifest_path.is_file() else None


__all__ = ["DiscoveredPlugin", "PluginDiscovery", "Source"]
