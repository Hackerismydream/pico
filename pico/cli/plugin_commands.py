"""``pico plugins`` — inspect installed memory / Tool plugins.

Reads ``PicoConfig.plugins`` plus the manifest-activated
:class:`PluginRegistry` and prints admitted plugins, their contributions, and
the memory backend selected by current config.

Use cases:

- "Where did this plugin come from?" — list the trusted automatic sources
  (bundled, operator-managed user directory, or installed entry point).
- "Why isn't my plugin loading?" — surface disabled or inactive manifests.
- "Which backend is active?" — resolve ``config.memory.backend`` against the
  admitted manifest set.

This is a read-only command at the contribution boundary: directory discovery
and registry activation do not import factory modules, and no backend or Tool is
built or started. Installed entry-point discovery may import the distribution's
package ``__init__`` to locate its manifest; those packages are operator-installed
code rather than checkout-controlled files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from pico.cli._helpers import load_runtime_config

console = Console()


def register(app: typer.Typer) -> None:
    """Attach the ``plugins`` command to ``app``."""

    @app.command()
    def plugins(
        config_path: Optional[str] = typer.Option(
            None,
            "--config",
            "-c",
            help="Path to config file (default: ~/.pico/config.json)",
        ),
        verbose: bool = typer.Option(
            False,
            "--verbose",
            "-v",
            help="Show manifest paths + factory references.",
        ),
    ) -> None:
        """List installed plugins + the active memory backend."""
        # Import lazily so ``pico --help`` doesn't pay for plugin discovery on
        # every invocation.
        from pico.cli._plugin_stack import plugin_discovery_sources
        from pico.plugin import PluginDiscovery, PluginRegistry

        ec_config = _load_ec_config(config_path)

        # Discover separately from activation so the table can show disabled
        # and inactive manifests, not just the admitted set. This uses exactly
        # the same trusted sources as live Runtime boot.
        discovery = PluginDiscovery(**plugin_discovery_sources())
        discovered = discovery.discover()

        registry = PluginRegistry()
        disabled = frozenset(ec_config.plugins.disabled)
        registry.activate(discovered, disabled=disabled)

        _render_plugin_table(discovered, registry, disabled, verbose=verbose)
        _render_backend_selection(ec_config, registry)


def _load_ec_config(config_path: str | None):
    """Load PicoConfig through the same config-path setup as other commands."""
    from pico.config.pico import load_pico_config

    load_runtime_config(config_path)
    return load_pico_config(
        Path(config_path) if config_path else None,
    )


def _render_plugin_table(
    discovered,
    registry,
    disabled,
    *,
    verbose: bool,
) -> None:
    """Print one row per discovered plugin with its status."""

    if not discovered:
        console.print(
            "[yellow]No plugins discovered.[/yellow] Reinstall Pico from the "
            "same distribution source, or run [bold]uv sync[/bold] from a "
            "Pico source checkout. Set "
            "[bold]memory.backend[/bold] to [bold]null[/bold], install a "
            "plugin distribution, or place an operator-managed manifest under "
            "[bold]~/.pico/plugins/[/bold].",
        )
        return

    table = Table(
        title="Pico plugins",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Plugin ID")
    table.add_column("Version")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Memory backends")
    if verbose:
        table.add_column("Factory")

    activated_ids = set(registry.activated_ids())
    for record in discovered:
        mf = record.manifest
        pid = mf.id
        if pid in disabled:
            status = "[red]disabled[/red]"
        elif pid in activated_ids:
            status = "[green]activated[/green]"
        elif not mf.enabled_by_default:
            status = "[dim]inactive (opt-in)[/dim]"
        else:
            status = "[yellow]not activated[/yellow]"
        backends = ", ".join(c.name for c in mf.contributes.memory_backends) or "(none)"

        row = [
            pid,
            mf.version,
            _source_label(record.source),
            status,
            backends,
        ]
        if verbose:
            factories = "; ".join(c.factory for c in mf.contributes.memory_backends)
            row.append(factories or "(none)")
        table.add_row(*row)
    console.print(table)


def _source_label(source) -> str:
    """Friendly label for a :class:`Source` enum value."""
    from pico.plugin import Source

    return {
        Source.ENTRY_POINTS: "entry_points",
        Source.PROJECT: "project",
        Source.USER: "user",
        Source.BUNDLED: "bundled",
    }.get(source, str(source))


def _render_backend_selection(ec_config, registry) -> None:
    """Show which memory backend the current config selects."""
    selected = ec_config.memory.backend
    if selected is None:
        console.print(
            "\n[bold]Active memory backend:[/bold] [dim]none[/dim] "
            "([italic]Memory is disabled; Local Skills remain available[/italic])",
        )
        return

    available = registry.memory_backend_names()
    if selected not in available:
        console.print(
            f"\n[bold]Active memory backend:[/bold] [red]{selected}[/red] [red](not available)[/red]",
        )
        console.print(
            f"  [dim]Registered: {', '.join(available) or '(none)'}[/dim]",
        )
        console.print(
            "  [dim]Runtime startup will fail closed until the selected "
            "backend is installed or memory.backend is set to null.[/dim]",
        )
        return

    owner_id = None
    for pid in registry.activated_ids():
        mf = registry.manifest_for(pid)
        if mf is None:
            continue
        for contribution in mf.contributes.memory_backends:
            if contribution.name == selected:
                owner_id = pid
                break
        if owner_id:
            break

    console.print(
        f"\n[bold]Active memory backend:[/bold] [green]{selected}[/green] [dim](from plugin: {owner_id})[/dim]",
    )
    console.print(
        f"  [dim]User id:  {ec_config.memory.user_id}[/dim]",
    )
