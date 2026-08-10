"""Plugin registry — records manifests and resolves factories on demand.

The registry deliberately splits admission from code execution:

1. **Activation** (:meth:`activate`) — admit manifests according to config,
   validate contribution-name conflicts, and record factory references. This
   phase does not import plugin Python code or widen ``sys.path``.
2. **Resolution / build** (:meth:`get_memory_backend_factory`,
   :meth:`get_tool_factory`, :meth:`build_memory_backend`, and
   :meth:`build_tool`) — import only the factory that the host actually asks
   to construct and cache the resolved callable.

Across-manifest name conflicts (two activated plugins both contributing the
same memory backend or Tool name) raise :class:`PluginConflictError`, which the
host treats as a startup failure. Discovery already deduplicates plugins by id;
the registry adds the second layer of deduplication on contribution names.
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pico.plugin.discover import DiscoveredPlugin, Source
from pico.plugin.manifest import PluginManifest
from pico.tracing import semconv, trace

logger = logging.getLogger(__name__)


MemoryBackendFactory = Callable[[Any], Any]
ToolFactory = Callable[[Any], Any]


class PluginError(Exception):
    """Base for plugin-system errors."""


class PluginConflictError(PluginError):
    """Two activated plugins contributed the same name into one slot."""


class PluginFactoryImportError(PluginError):
    """A manifest factory reference could not be imported or resolved."""


class PluginNotFoundError(PluginError):
    """The user asked for a contribution no activated plugin provides."""


@dataclass(frozen=True)
class _ActivatedFactory:
    """Unresolved factory reference plus provenance for diagnostics."""

    plugin_id: str
    name: str
    ref: str
    source: Source
    location: Path | None


class PluginRegistry:
    """Single registration center for admitted plugin contributions."""

    def __init__(self) -> None:
        self._manifests: dict[str, PluginManifest] = {}
        self._memory_backends: dict[str, _ActivatedFactory] = {}
        self._tools: dict[str, _ActivatedFactory] = {}
        self._resolved_factories: dict[tuple[str, str], MemoryBackendFactory] = {}

    # ── Activation ───────────────────────────────────────────────

    def activate(
        self,
        discovered: list[DiscoveredPlugin],
        *,
        disabled: frozenset[str] = frozenset(),
    ) -> None:
        """Admit manifests without importing plugin Python code.

        A plugin is admitted when its id is not disabled and its manifest is
        enabled by default. Contribution conflicts are rejected using manifest
        data alone. Factory imports are deferred until the corresponding
        contribution is actually looked up or built.
        """
        for d in discovered:
            mf = d.manifest
            if mf.id in disabled:
                logger.info("plugin %s disabled by user config", mf.id)
                continue
            if not mf.enabled_by_default:
                logger.info(
                    "plugin %s not enabled by default; skipping (use explicit opt-in once supported)",
                    mf.id,
                )
                continue
            self._activate_one(mf, source=d.source, location=d.location)

    def _activate_one(
        self,
        mf: PluginManifest,
        *,
        source: Source,
        location: Path | None,
    ) -> None:
        if mf.id in self._manifests:
            raise PluginConflictError(
                f"plugin id {mf.id!r} activated twice",
            )
        self._manifests[mf.id] = mf

        for contribution in mf.contributes.memory_backends:
            if contribution.name in self._memory_backends:
                prev = self._memory_backends[contribution.name]
                raise PluginConflictError(
                    f"memory_backend {contribution.name!r} contributed by both {prev.plugin_id!r} and {mf.id!r}",
                )
            self._memory_backends[contribution.name] = _ActivatedFactory(
                plugin_id=mf.id,
                name=contribution.name,
                ref=contribution.factory,
                source=source,
                location=location,
            )
            logger.debug(
                "registered memory_backend %s from %s",
                contribution.name,
                mf.id,
            )

        for tool in mf.contributes.tools:
            if tool.name in self._tools:
                prev = self._tools[tool.name]
                raise PluginConflictError(
                    f"tool {tool.name!r} contributed by both {prev.plugin_id!r} and {mf.id!r}",
                )
            self._tools[tool.name] = _ActivatedFactory(
                plugin_id=mf.id,
                name=tool.name,
                ref=tool.factory,
                source=source,
                location=location,
            )
            logger.debug("registered tool %s from %s", tool.name, mf.id)

    @staticmethod
    def _ensure_importable(source: Source, location: Path | None) -> None:
        """Expose one file-based plugin directory immediately before import.

        USER / PROJECT plugins may ship a Python package next to their
        manifest. Their directory is appended only when a host actually asks
        to resolve one of their factories; manifest discovery and activation
        remain code-free. Appending instead of prepending preserves installed
        package priority. The process-wide import surface remains widened after
        resolution, which is why automatic repository-level discovery is not a
        supported host source.
        """
        if source not in (Source.USER, Source.PROJECT) or location is None:
            return
        plugin_dir = str(location.parent)
        if plugin_dir not in sys.path:
            sys.path.append(plugin_dir)

    @staticmethod
    def _resolve_factory(plugin_id: str, ref: str) -> MemoryBackendFactory:
        """Import ``module`` and return the referenced callable."""
        module_path, attr = ref.split(":", 1)
        try:
            mod = importlib.import_module(module_path)
        except Exception as e:
            raise PluginFactoryImportError(
                f"plugin {plugin_id!r}: importing {module_path!r} failed: {e}",
            ) from e
        try:
            obj = getattr(mod, attr)
        except AttributeError as e:
            raise PluginFactoryImportError(
                f"plugin {plugin_id!r}: {module_path!r} has no attribute {attr!r}",
            ) from e
        if not callable(obj):
            raise PluginFactoryImportError(
                f"plugin {plugin_id!r}: {ref} resolved to a non-callable {type(obj).__name__}",
            )
        return obj  # type: ignore[return-value]

    def _get_factory(
        self,
        kind: str,
        entry: _ActivatedFactory,
    ) -> MemoryBackendFactory:
        key = (kind, entry.name)
        cached = self._resolved_factories.get(key)
        if cached is not None:
            return cached
        self._ensure_importable(entry.source, entry.location)
        factory = self._resolve_factory(entry.plugin_id, entry.ref)
        self._resolved_factories[key] = factory
        return factory

    # ── Introspection ────────────────────────────────────────────

    def activated_ids(self) -> list[str]:
        """Stable-ordered list of admitted plugin ids."""
        return sorted(self._manifests)

    def memory_backend_names(self) -> list[str]:
        """Stable-ordered list of registered memory-backend names."""
        return sorted(self._memory_backends)

    def get_memory_backend_factory(self, name: str) -> MemoryBackendFactory:
        """Resolve the backend factory for ``name`` on first use."""
        try:
            entry = self._memory_backends[name]
        except KeyError as e:
            raise PluginNotFoundError(
                f"no memory_backend named {name!r} (registered: {self.memory_backend_names()})",
            ) from e
        return self._get_factory("memory_backend", entry)

    def tool_names(self) -> list[str]:
        """Stable-ordered list of registered plugin-tool names."""
        return sorted(self._tools)

    def tool_plugin_id(self, name: str) -> str | None:
        """Plugin id that contributed tool ``name``, or None."""
        entry = self._tools.get(name)
        return entry.plugin_id if entry is not None else None

    def get_tool_factory(self, name: str) -> ToolFactory:
        """Resolve the Tool factory for ``name`` on first use."""
        try:
            entry = self._tools[name]
        except KeyError as e:
            raise PluginNotFoundError(
                f"no tool named {name!r} (registered: {self.tool_names()})",
            ) from e
        return self._get_factory("tool", entry)

    def manifest_for(self, plugin_id: str) -> PluginManifest | None:
        """Return the manifest of an admitted plugin, or None."""
        return self._manifests.get(plugin_id)

    # ── Build ────────────────────────────────────────────────────

    @trace.instrument("plugin.load", extract=semconv.plugin_load("memory_backend"))
    def build_memory_backend(
        self,
        name: str,
        *,
        config: dict[str, Any],
        services: "ServiceLocator",
        logger: logging.Logger | None = None,
    ) -> Any:
        """Resolve and invoke the selected memory-backend factory."""
        from pico.plugin.context import PluginContext

        factory = self.get_memory_backend_factory(name)
        ctx = PluginContext(
            config=config,
            services=services,
            logger=logger or logging.getLogger(f"pico.plugin.{name}"),
        )
        return factory(ctx)

    @trace.instrument("plugin.load", extract=semconv.plugin_load("tool"))
    def build_tool(
        self,
        name: str,
        *,
        config: dict[str, Any],
        services: "ServiceLocator",
        logger: logging.Logger | None = None,
    ) -> Any:
        """Resolve and invoke the selected Tool factory."""
        from pico.plugin.context import PluginContext

        factory = self.get_tool_factory(name)
        ctx = PluginContext(
            config=config,
            services=services,
            logger=logger or logging.getLogger(f"pico.plugin.{name}"),
        )
        return factory(ctx)


from pico.plugin.context import ServiceLocator  # noqa: E402

__all__ = [
    "MemoryBackendFactory",
    "PluginConflictError",
    "PluginError",
    "PluginFactoryImportError",
    "PluginNotFoundError",
    "PluginRegistry",
    "ToolFactory",
]
