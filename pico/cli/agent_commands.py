"""Top-level ``run`` command + its dedicated helpers.

This module owns:

- The interactive ``pico run`` REPL command body (multiline paste,
  history, agent-loop wiring).
- A small bundle of helpers used only by that command: prompt-toolkit
  session init, terminal restore, TTY-flush, response rendering, exit
  detection.

``commands.py`` registers the command via :func:`register`.
"""

from __future__ import annotations

import asyncio
import signal
import sys

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from pico import __logo__
from pico.cli._helpers import (
    load_runtime_config,
    make_provider,
    print_deprecated_memory_window_notice,
    warn_about_pending_cli_reminders,
)
from pico.utils.helpers import sync_workspace_templates

console = Console()


# ---------------------------------------------------------------------------
# Module-level state (interactive REPL only)
# ---------------------------------------------------------------------------

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


# ---------------------------------------------------------------------------
# Helpers (private to this module)
# ---------------------------------------------------------------------------


def _stdout_isatty() -> bool:
    """Whether stdout is an interactive TTY (seam for the onboarding gate test;
    CliRunner swaps ``sys.stdout`` for a non-TTY buffer)."""
    return sys.stdout.isatty()


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from pico.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} Pico[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        # raw=True passes ANSI escape sequences through verbatim. Without
        # this, background Cron coroutines that
        # print rich-styled output while the user sits at this prompt get
        # their ESC bytes mangled — visible as ?[36m...?[0m garbage.
        with patch_stdout(raw=True):
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Attach the ``run`` command to ``app``."""

    @app.command("run")
    def agent(
        message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
        session_id: str | None = typer.Option(
            None,
            "--session",
            "-s",
            help=(
                "Full session key (channel:chat_id), any channel. By default "
                "a fresh cli session is minted per invocation. The legacy "
                "'direct' session remains reachable via --resume direct."
            ),
        ),
        continue_: bool = typer.Option(False, "--continue", "-c", help="Continue the most recent cli session"),
        resume: str | None = typer.Option(None, "--resume", "-r", help="Resume session by bare id or unique prefix"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", help="Config file path"),
        markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
        logs: bool = typer.Option(False, "--logs/--no-logs", help="Show Pico runtime logs during chat"),
    ):
        """Interact with the agent directly."""
        if sum((session_id is not None, continue_, resume is not None)) > 1:
            raise typer.BadParameter("--session, --continue and --resume are mutually exclusive")

        # Startup gate: when the required config (a provider key + default
        # model) is missing, run the onboarding wizard first. Only on an
        # interactive TTY — scripted one-shots (`-m`) and non-TTY pipes must
        # fail loudly later rather than block on prompts.
        from pico.cli.onboard_commands import _is_config_populated

        if message is None and _stdout_isatty() and not _is_config_populated():
            from pico.cli.onboard_commands import ensure_configured_or_onboard

            ensure_configured_or_onboard()

        from loguru import logger

        from pico.cli._cron_handler import make_on_cron_job
        from pico.cli._runtime_assembly import assemble_runtime
        from pico.config.paths import get_cron_dir, resolve_foreground_paths
        from pico.config.pico import load_pico_config
        from pico.proactive_engine.schedulers.cron.service import CronService
        from pico.session.manager import SessionManager, new_chat_id

        # load_runtime_config must run FIRST: it calls set_config_path() so
        # that subsequent load_pico_config() reads from --config, not the
        # default ~/.pico/config.json. Otherwise skill_forge from --config is
        # silently ignored.
        config = load_runtime_config(config, workspace)
        paths = resolve_foreground_paths(config, workspace=workspace)
        ec_config = load_pico_config()
        print_deprecated_memory_window_notice(config)
        sync_workspace_templates(paths.state)

        provider = make_provider(config)
        session_manager = SessionManager(paths.state)

        # New-session-by-default: independent one-shots don't bleed into each other.
        if resume is not None:
            from pico.cli.session_commands import resolve_session

            session_id = resolve_session(session_manager, resume)
        elif continue_:
            recent = session_manager.find_most_recent_chat_id("cli")
            if recent is None:
                console.print("[dim]no previous cli session — starting fresh[/dim]")
                recent = new_chat_id()
            session_id = f"cli:{recent}"
        elif session_id is None:
            session_id = f"cli:{new_chat_id()}"
        else:
            from pico.cli.session_commands import resolve_session_cross_channel

            session_id = resolve_session_cross_channel(session_manager, session_id)

        # Create cron service (callback set below once the agent exists).
        # allowed_channels={"cli"} prevents this REPL from claiming reminders
        # created in a messaging Channel; those should be delivered by the
        # gateway which has the real channel adapters wired up.
        cron_store_path = get_cron_dir() / "jobs.json"
        cron = CronService(cron_store_path, allowed_channels={"cli"})

        if logs:
            logger.enable("pico")
        else:
            logger.disable("pico")

        runtime = assemble_runtime(
            config,
            ec_config,
            provider=provider,
            cron_service=cron,
            interactive=message is None,
            session_manager=session_manager,
            paths=paths,
        )
        agent_loop = runtime.agent_loop
        # REPL has no real ChannelManager — provide a minimal shim that
        # reports "cli" as the sole enabled channel so cli reminders take
        # the pass-through path (deliver to REPL stdout via the Spine outlet).
        from types import SimpleNamespace

        cli_shim = SimpleNamespace(enabled_channels=["cli"])
        # cron.on_job is wired inside run_interactive once the spine scheduler
        # exists — cron reminders submit CRON turns through it.

        # Show spinner when logs are off (no output to miss); skip when logs are on
        def _thinking_ctx():
            if logs:
                from contextlib import nullcontext

                return nullcontext()
            # Animated spinner is safe to use with prompt_toolkit input handling
            return console.status("[dim]Pico is thinking...[/dim]", spinner="dots")

        if message:
            # Single message mode — one USER turn through spine (submit -> lane ->
            # run_turn -> hub -> CliOutlet), with the legacy cli/direct defaults
            # (channel="cli", chat_id="direct", session_key=session_id). Progress
            # renders via the CliOutlet, gated by the same two config flags the bus
            # path honored (send_progress / send_tool_hints).
            from pico.cli._repl_spine import build_repl
            from pico.spine import ChatType, Origin, Source, TurnRequest

            async def run_once():
                teardown = None
                try:
                    await runtime.start_memory_backend()
                    # Build inside the running loop: Scheduler pins its home loop in
                    # __init__, so build_repl must not run in the sync prologue.
                    ch = agent_loop.channels_config
                    scheduler, hub, teardown = build_repl(
                        agent_loop,
                        "cli",
                        lambda t: _print_agent_response(t, render_markdown=markdown),
                        render_notice=lambda c: console.print(f"  [dim]↳ {c}[/dim]"),
                        render_error=lambda c: console.print(f"[red]{c}[/red]"),
                        send_progress=bool(ch.send_progress) if ch else False,
                        send_tool_hints=bool(ch.send_tool_hints) if ch else False,
                    )
                    # A one-shot spawn rarely finishes before the hard-exit below (same
                    # as the bus path), but wire submit for parity with REPL/TUI.
                    agent_loop.subagents.set_submit(scheduler.submit)
                    with _thinking_ctx():
                        handle = scheduler.submit(
                            TurnRequest(
                                origin=Origin.USER,
                                source=Source(
                                    channel="cli",
                                    chat_id="direct",
                                    sender_id="user",
                                    chat_type=ChatType.DM,
                                ),
                                text=message,
                                conversation=session_id,
                            )
                        )
                        outcome = await handle.result()
                    await hub.wait_idle("cli")  # render barrier: CliOutlet caught up
                    return outcome is not None
                finally:
                    try:
                        if teardown is not None:
                            await teardown()
                    finally:
                        await runtime.close()

            if not asyncio.run(run_once()):
                raise typer.Exit(1)
            # Native runtimes loaded by the agent loop (lancedb's Rust/tokio
            # thread, torch) segfault during interpreter finalization. The exit
            # chokepoint in pico.cli.commands.run hard-exits past finalization
            # when that hazard is live, so this path just returns normally.
        else:
            # Interactive mode — user turns run through spine (submit -> lane ->
            # hub -> CliOutlet); Cron turns use the same spine and hub.
            from pico.cli._repl_spine import build_repl, run_repl_loop

            _init_prompt_session()
            console.print(f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

            if ":" in session_id:
                cli_channel, cli_chat_id = session_id.split(":", 1)
            else:
                cli_channel, cli_chat_id = "cli", session_id

            def _handle_signal(signum, frame):
                sig_name = signal.Signals(signum).name
                _restore_terminal()
                console.print(f"\nReceived {sig_name}, goodbye!")
                sys.exit(0)

            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
            # SIGHUP is not available on Windows
            if hasattr(signal, "SIGHUP"):
                signal.signal(signal.SIGHUP, _handle_signal)
            # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
            # SIGPIPE is not available on Windows
            if hasattr(signal, "SIGPIPE"):
                signal.signal(signal.SIGPIPE, signal.SIG_IGN)

            async def run_interactive():
                runtime_task = None
                teardown = None
                try:
                    await runtime.start_memory_backend()
                    # Build the spine before starting cron: cron jobs submit CRON
                    # turns through this scheduler, and on_job must be wired
                    # before cron.start() so an immediately-firing job has its
                    # callback. Scheduler pins its home loop here (run_interactive is
                    # async) — it must not move to the sync prologue.
                    _ch = agent_loop.channels_config
                    scheduler, hub, teardown = build_repl(
                        agent_loop,
                        cli_channel,
                        lambda t: _print_agent_response(t, render_markdown=markdown),
                        render_notice=lambda c: console.print(f"  [dim]↳ {c}[/dim]"),
                        render_error=lambda c: console.print(f"[red]{c}[/red]"),
                        send_progress=bool(_ch.send_progress) if _ch else False,
                        send_tool_hints=bool(_ch.send_tool_hints) if _ch else False,
                    )
                    # Subagent result re-injection submits a SUBAGENT-origin turn.
                    agent_loop.subagents.set_submit(scheduler.submit)
                    # Cron reminders run as CRON-origin turns through the spine
                    # scheduler and are delivered by the hub -> CliOutlet.
                    cron.on_job = make_on_cron_job(
                        hub,
                        submit=scheduler.submit,
                        channel_manager=cli_shim,
                        session_manager=session_manager,
                        default_channel="cli",
                    )
                    # Start cron so scheduled reminders ("remind me in 1 minute")
                    # actually fire — previously the REPL created a CronService but
                    # never started its tick loop, so jobs just sat in jobs.json.
                    await cron.start()

                    # The keep-alive starts only after synchronous composition
                    # succeeds. Yield once so stop() cannot run before run() has
                    # established its running state.
                    runtime_task = asyncio.create_task(agent_loop.run())
                    await asyncio.sleep(0)

                    def _on_exit() -> None:
                        _restore_terminal()
                        console.print("\nGoodbye!")

                    def _slash(command: str) -> bool:
                        from pico.cli._repl_slash import handle_repl_slash

                        return handle_repl_slash(command, console=console)

                    await run_repl_loop(
                        read_input=_read_interactive_input_async,
                        submit=scheduler.submit,
                        wait_idle=hub.wait_idle,
                        channel=cli_channel,
                        chat_id=cli_chat_id,
                        is_exit=_is_exit_command,
                        handle_slash=_slash,
                        thinking=_thinking_ctx,
                        on_exit=_on_exit,
                    )
                finally:
                    try:
                        cron.stop()
                        agent_loop.stop()
                        if teardown is not None:
                            await teardown()
                        if runtime_task is not None:
                            await asyncio.gather(runtime_task, return_exceptions=True)
                    finally:
                        await runtime.close()
                    warn_about_pending_cli_reminders(cron, config)

            asyncio.run(run_interactive())


__all__ = ["register"]
