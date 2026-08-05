"""CLI assembly helper for the plugin / memory-backend stack.

Two functions that bridge the gap between the runtime config (user-facing
settings under ``plugins`` / ``memory``) and the runtime objects
AgentLoop expects (a ready-to-use :class:`MemoryBackend` instance):

- :func:`build_plugin_registry` — discover all installed plugins
  (bundled + user-level + project-level + pip entry points), filter
  by ``config.plugins.disabled``, return an activated registry.
- :func:`maybe_build_memory_backend` — resolve ``config.memory.backend``
  to a concrete :class:`MemoryBackend` instance via the registry, or
  return ``None`` when no backend is selected / the requested
  contribution isn't available.

An explicit ``memory.backend`` selection is fail-closed: activation,
resolution, and construction errors remain visible to the Runtime host.
Only ``memory.backend = null`` disables Memory.

Lifecycle (``backend.start()`` / ``backend.stop()``) belongs to the concrete
``RuntimeAssembly``. These helpers only construct plugin contributions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pico.plugin import (
    PluginNotFoundError,
    PluginRegistry,
    ServiceLocator,
    assemble_plugin_registry,
)
from pico.product import get_product_home, get_workspace_state_dir

if TYPE_CHECKING:
    from pico.config.pico import PicoConfig
    from pico.memory_engine import MemoryBackend

logger = logging.getLogger(__name__)


def plugin_discovery_sources() -> dict:
    """Resolve the four discovery-source locations the host scans.

    Shared by :func:`build_plugin_registry` (live boot) and the
    ``pico plugins`` CLI command so both see the same set:

    - bundled — ``pico/plugin/memory/`` inside the package.
    - user    - ``~/.pico/plugins/``.
    - project - ``./.pico/plugins/``.
    - entry_points - the ``pico.plugins`` group.
    """
    import pico

    return {
        "bundled_dir": Path(pico.__path__[0]) / "plugin" / "memory",
        "user_dir": get_product_home() / "plugins",
        "project_dir": get_workspace_state_dir(Path.cwd()) / "plugins",
        "entry_points_group": "pico.plugins",
    }


def build_plugin_registry(
    config: "PicoConfig",
) -> PluginRegistry:
    """Discover + activate every installed plugin admitted by ``config``.

    Reads ``config.plugins.disabled`` and forwards it to
    :func:`assemble_plugin_registry`. Activation errors propagate so a
    configured backend cannot silently disappear.

    Discovery spans four sources (priority bundled > user > project >
    entry_points):

    - **bundled** — ``pico/plugin/memory/<id>/`` shipped inside the
      Pico package.
    - **user** - ``~/.pico/plugins/<id>/`` drop-in directories.
    - **project** - ``./.pico/plugins/<id>/`` drop-in directories.
    - **entry_points** - the ``pico.plugins`` group, where
      third-party pip-installed plugins register their factories.
    """
    disabled = frozenset(config.plugins.disabled)
    return assemble_plugin_registry(
        **plugin_discovery_sources(),
        disabled=disabled,
    )


def maybe_build_memory_backend(
    workspace: Path,
    config: "PicoConfig",
    *,
    registry: PluginRegistry | None = None,
) -> "MemoryBackend | None":
    """Construct the configured memory backend, if any.

    Resolution order:

    1. If ``config.memory.backend`` is ``None``, return ``None``
       immediately — user explicitly disabled the plugin path.
    2. Look up the backend factory in the (possibly host-supplied)
       :class:`PluginRegistry`. Missing configured contributions raise.
    3. Resolve the per-plugin config slice from
       ``config.plugins.config`` — first by plugin id, then by backend
       contribution name as a fallback.

    The returned backend has **not** been ``await``-started. Runtime Assembly
    owns its start / stop lifecycle, while each host decides when startup fits
    its interaction policy.
    """
    name = config.memory.backend
    if name is None:
        return None
    if registry is None:
        registry = build_plugin_registry(config)
    plugin_slice = _resolve_plugin_config_slice(registry, config, name)
    services = ServiceLocator(workspace=workspace)
    try:
        return registry.build_memory_backend(
            name,
            config=plugin_slice,
            services=services,
        )
    except PluginNotFoundError as exc:
        if name == "everos":
            raise PluginNotFoundError(
                "memory.backend='everos' is no longer supported; initialize "
                "CodeCairn and set memory.backend to 'codecairn', or set it to "
                "null. Existing EverOS data is left untouched"
            ) from exc
        if name != "codecairn":
            raise
        raise PluginNotFoundError(
            "configured CodeCairn plugin is unavailable; reinstall Pico from "
            "the same distribution source, or run 'uv sync' from a Pico source "
            "checkout. Set memory.backend to null to disable Memory explicitly"
        ) from exc


def build_plugin_tools(
    workspace: Path,
    config: "PicoConfig",
    *,
    registry: PluginRegistry | None = None,
) -> list:
    """Construct every plugin-contributed tool admitted by ``config``.

    Mirrors :func:`maybe_build_memory_backend` but for the ``tools``
    contribution point: walks the activated registry's tool names,
    resolves each owning plugin's config slice, and builds the tool via
    :meth:`PluginRegistry.build_tool`. Lenient by design — a single
    tool's construction failure is logged and skipped so one bad plugin
    can't keep the agent from booting. A factory may also return ``None``
    to deliberately decline contribution (e.g. an optional dependency is
    absent); that's skipped quietly, not treated as a failure. The host
    registers the returned tools into the agent's :class:`ToolRegistry`.

    Returns an empty list when no plugin contributes a tool.
    """
    if registry is None:
        registry = build_plugin_registry(config)
    names = registry.tool_names()
    if not names:
        return []
    services = ServiceLocator(workspace=workspace)
    slices = config.plugins.config
    tools = []
    for name in names:
        plugin_id = registry.tool_plugin_id(name)
        plugin_slice = (plugin_id and slices.get(plugin_id)) or slices.get(name) or {}
        try:
            tool = registry.build_tool(
                name,
                config=plugin_slice,
                services=services,
            )
        except Exception as e:
            logger.warning(
                "plugin tool %r factory raised at construction (%s); skipping it.",
                name,
                e,
            )
            continue
        # A factory may return None to decline contribution at runtime
        # (e.g. an optional dependency isn't installed). That's a clean
        # opt-out, not a failure — skip it without the warning.
        if tool is None:
            logger.debug(
                "plugin tool %r factory opted out (returned None); skipping it.",
                name,
            )
            continue
        tools.append(tool)
    return tools


def _resolve_plugin_config_slice(
    registry: PluginRegistry,
    config: "PicoConfig",
    backend_name: str,
) -> dict:
    """Pick the right ``config.plugins.config[...]`` entry for a backend.

    Tries two keys, in order:

    1. The **plugin id** that contributes ``backend_name`` (canonical,
       e.g. ``"codecairn-memory"`` - comes from the manifest's
       ``[plugin] id`` field).
    2. The **backend contribution name** itself
       (e.g. ``"codecairn"`` - friendlier for handwritten config files).

    Returns an empty dict when neither key is present, so the plugin
    factory receives a deterministic shape and applies its own
    defaults.
    """
    slices = config.plugins.config
    plugin_id = _plugin_id_for_backend(registry, backend_name)
    if plugin_id is not None and plugin_id in slices:
        return slices[plugin_id]
    if backend_name in slices:
        return slices[backend_name]
    return {}


def _plugin_id_for_backend(
    registry: PluginRegistry,
    backend_name: str,
) -> str | None:
    """Reverse-lookup the plugin id that contributes ``backend_name``.

    Returns ``None`` when no activated plugin contributes the named
    backend — the caller (config resolver) treats that as "fall
    through to the contribution-name key".
    """
    for plugin_id in registry.activated_ids():
        mf = registry.manifest_for(plugin_id)
        if mf is None:
            continue
        for contribution in mf.contributes.memory_backends:
            if contribution.name == backend_name:
                return plugin_id
    return None


__all__ = [
    "build_plugin_registry",
    "build_plugin_tools",
    "maybe_build_memory_backend",
]
