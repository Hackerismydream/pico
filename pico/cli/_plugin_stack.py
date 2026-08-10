"""CLI assembly helper for the plugin / memory-backend stack.

Two functions bridge the gap between user-facing settings under ``plugins`` /
``memory`` and the runtime objects :class:`AgentLoop` expects:

- :func:`build_plugin_registry` discovers trusted host plugin sources (bundled,
  operator-managed user plugins, and installed entry points), filters them by
  ``config.plugins.disabled``, and returns a manifest-activated registry.
- :func:`maybe_build_memory_backend` resolves ``config.memory.backend`` to a
  concrete :class:`MemoryBackend` instance, or returns ``None`` only when no
  backend is selected.

Repository-local executable plugins are intentionally not auto-discovered.
Starting Pico in a checkout must not import Python controlled by that checkout
before Tool confirmation or Sandbox policy applies. Project-specific behavior
belongs in Local Skills, MCP configuration, or an operator-installed plugin.

An explicit ``memory.backend`` selection is fail-closed: factory resolution and
construction errors remain visible to the Runtime host. Only
``memory.backend = null`` disables Memory.

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
from pico.product import get_product_home

if TYPE_CHECKING:
    from pico.config.pico import PicoConfig
    from pico.memory_engine import MemoryBackend

logger = logging.getLogger(__name__)


def plugin_discovery_sources() -> dict:
    """Resolve the trusted discovery sources scanned by Pico hosts.

    Shared by :func:`build_plugin_registry` (live boot) and the
    ``pico plugins`` CLI command so both see the same set:

    - bundled — ``pico/plugin/memory/`` inside the installed package;
    - user — ``~/.pico/plugins/`` managed by the operator;
    - entry points — installed distributions in the ``pico.plugins`` group.

    ``project_dir`` is explicitly ``None``. A repository must not gain an
    executable startup hook merely by containing ``.pico/plugins``.
    """
    import pico

    return {
        "bundled_dir": Path(pico.__path__[0]) / "plugin" / "memory",
        "user_dir": get_product_home() / "plugins",
        "project_dir": None,
        "entry_points_group": "pico.plugins",
    }


def build_plugin_registry(
    config: "PicoConfig",
) -> PluginRegistry:
    """Discover and admit installed plugins allowed by ``config``.

    Reads ``config.plugins.disabled`` and forwards it to
    :func:`assemble_plugin_registry`. Admission validates manifest conflicts
    without importing factory modules. Factory failures surface later when a
    selected backend or admitted Tool is actually constructed.

    Discovery priority is bundled > user > entry points. Automatic
    repository-level discovery is deliberately excluded because Pico has no
    project-plugin trust or consent handshake.
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

    1. If ``config.memory.backend`` is ``None``, return ``None`` immediately —
       the user explicitly disabled the plugin path.
    2. Look up the backend factory in the possibly host-supplied registry.
       Missing configured contributions raise.
    3. Resolve the per-plugin config slice from ``config.plugins.config`` —
       first by plugin id, then by backend contribution name as a fallback.

    The returned backend has not been ``await``-started. Runtime Assembly owns
    its start/stop lifecycle, while each host decides when startup fits its
    interaction policy.
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
    """Construct every plugin-contributed Tool admitted by ``config``.

    Mirrors :func:`maybe_build_memory_backend` but for the ``tools``
    contribution point: walk the registry's Tool names, resolve each owning
    plugin's config slice, and build the Tool through
    :meth:`PluginRegistry.build_tool`. A single Tool construction failure is
    logged and skipped so one operator-installed plugin cannot keep the Agent
    from booting. A factory may also return ``None`` to decline contribution
    when an optional dependency is absent; that is skipped quietly.

    Returns an empty list when no plugin contributes a Tool.
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

    Tries the contributing plugin id first and the backend contribution name
    second. Returns an empty dict when neither key is present.
    """
    slices = config.plugins.config
    plugin_id = _plugin_id_for_backend(registry, backend_name)
    if plugin_id is not None and plugin_id in slices:
        return slices[plugin_id]
    return slices.get(backend_name, {})


def _plugin_id_for_backend(
    registry: PluginRegistry,
    backend_name: str,
) -> str | None:
    """Reverse-lookup the plugin id that contributes ``backend_name``."""
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
    "plugin_discovery_sources",
]
