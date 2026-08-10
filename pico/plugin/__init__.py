"""Plugin foundation.

The public contribution points are ``memory_backends`` and ``tools``. The
system keeps two load-bearing boundaries:

1. **Manifests are pure data.** ``PluginManifest.from_toml_path`` reads TOML
   only. Directory discovery and registry activation validate ids, enablement,
   and contribution conflicts without importing factory modules. Installed
   entry-point discovery may import an operator-installed package to locate its
   manifest.
2. **Factories are referenced by ``module.path:callable`` strings.** The
   registry imports and caches a factory only when a host actually asks to
   resolve or build that contribution. Listing plugins therefore remains a
   manifest-only operation at the contribution boundary.

Pico hosts automatically scan bundled plugins, operator-managed user plugins,
and installed ``pico.plugins`` entry points. Repository-local executable
plugins are not an automatic discovery source.
"""

from __future__ import annotations

from pico.plugin.bootstrap import assemble_plugin_registry
from pico.plugin.context import PluginContext, ServiceLocator
from pico.plugin.discover import DiscoveredPlugin, PluginDiscovery, Source
from pico.plugin.manifest import (
    Contributes,
    MemoryBackendContribution,
    PluginManifest,
    ToolContribution,
)
from pico.plugin.registry import (
    MemoryBackendFactory,
    PluginConflictError,
    PluginError,
    PluginFactoryImportError,
    PluginNotFoundError,
    PluginRegistry,
    ToolFactory,
)

__all__ = [
    "Contributes",
    "DiscoveredPlugin",
    "assemble_plugin_registry",
    "MemoryBackendContribution",
    "MemoryBackendFactory",
    "PluginConflictError",
    "PluginContext",
    "PluginDiscovery",
    "PluginError",
    "PluginFactoryImportError",
    "PluginManifest",
    "PluginNotFoundError",
    "PluginRegistry",
    "ServiceLocator",
    "Source",
    "ToolContribution",
    "ToolFactory",
]
