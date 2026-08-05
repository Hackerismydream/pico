"""Pico CLI entry-point.

This module wires together every top-level command and every subcommand
group. The actual implementations live in per-feature modules:

- Top-level commands (each exposes a ``register(app)`` function):
    - ``run``      → ``pico/cli/agent_commands.py``
    - ``doctor``   → ``pico/cli/doctor_commands.py``
    - ``evolve``   → ``pico/cli/evolve_commands.py``
    - ``gateway``  → ``pico/cli/gateway_commands.py``
    - ``onboard``  → ``pico/cli/onboard_commands.py``
    - ``status``   → ``pico/cli/status_commands.py``

- Subcommand groups (each exposes a typer ``*_app`` instance):
    - ``channels`` → ``pico/cli/channel_commands.py``
    - ``cron``     → ``pico/cli/cron_commands.py``
    - ``provider`` → ``pico/cli/provider_commands.py``
    - ``sessions`` → ``pico/cli/session_commands.py``
    - ``skills``   → ``pico/cli/skill_commands.py``

Shared helpers used across multiple command modules live in
``pico/cli/_helpers.py``.
"""

import os
import sys

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from rich.console import Console

from pico import __logo__, __version__

app = typer.Typer(
    name="pico",
    help=f"{__logo__} Pico - compact, composable, benchmark-gated Agent Harness with an opt-in evolution path",
    no_args_is_help=False,
    invoke_without_command=True,
)
console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} Pico v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
    check: bool = typer.Option(False, "--check", help="Smoke-test the native TUI and exit."),
    dev: bool = typer.Option(False, "--dev", help="Run the native TUI from TypeScript source."),
    color: str | None = typer.Option(
        None,
        "--color",
        help="Force TUI color output: auto | truecolor | 256 | 16 | none.",
    ),
    print_colors: bool = typer.Option(False, "--print-colors", help="Print the resolved TUI color palette and exit."),
    preview_colors: bool = typer.Option(False, "--preview-colors", help="Preview TUI color tokens and exit."),
):
    """Pico - compact, composable, benchmark-gated Agent Harness with an opt-in evolution path.

    Bare ``pico`` runs the startup gate and enters the native TUI.
    """
    if ctx.invoked_subcommand is not None:
        return
    from pico.cli.tui_commands import launch_tui

    launch_tui(
        check=check,
        dev=dev,
        color=color,
        print_colors=print_colors,
        preview_colors=preview_colors,
    )


# ============================================================================
# Top-level command registrations
# ============================================================================

from pico.cli import (
    agent_commands,
    doctor_commands,
    evolve_commands,
    gateway_commands,
    onboard_commands,
    plugin_commands,
    status_commands,
    tracing_commands,
)

onboard_commands.register(app)
gateway_commands.register(app)
agent_commands.register(app)
status_commands.register(app)
doctor_commands.register(app)
evolve_commands.register(app)
plugin_commands.register(app)
tracing_commands.register(app)


# ============================================================================
# Subcommand registrations
# ============================================================================

from pico.cli.channel_commands import channels_app
from pico.cli.cron_commands import cron_app
from pico.cli.provider_commands import provider_app
from pico.cli.sandbox_commands import sandbox_app
from pico.cli.skill_commands import skill_app

app.add_typer(channels_app, name="channels")
app.add_typer(cron_app, name="cron")
app.add_typer(provider_app, name="provider")
app.add_typer(sandbox_app, name="sandbox", hidden=True)
app.add_typer(skill_app, name="skills")

from pico.cli.session_commands import session_app

app.add_typer(session_app, name="sessions")


def run() -> None:
    """Console-script entry point.

    Runs the Typer app, then hard-exits past CPython interpreter finalization
    when a native runtime that segfaults at finalization is live (lancedb's
    Rust/tokio background thread — see :mod:`pico.cli._exit`). Any command that
    builds the agent loop starts that thread, so guarding here covers them all
    at once. CliRunner invokes ``app`` directly and never reaches this wrapper,
    so in-process test hosts keep normal exit semantics.
    """
    from pico.cli._exit import flush_and_hard_exit, lancedb_finalization_hazard
    from pico.config.loader import ConfigReadError

    try:
        app()
    except ConfigReadError as exc:
        # A config-write command (channels/provider/onboard) hit an
        # unparseable config. The write layer already refused (file untouched);
        # surface it cleanly here, once, for every command instead of a traceback.
        from rich.console import Console

        Console(stderr=True).print(f"[red]✗[/red] {exc}")
        raise SystemExit(1) from exc
    except SystemExit as exc:
        code = exc.code
        if not isinstance(code, int):
            code = 0 if code is None else 1
        if lancedb_finalization_hazard():
            flush_and_hard_exit(code)
        raise


if __name__ == "__main__":
    run()
