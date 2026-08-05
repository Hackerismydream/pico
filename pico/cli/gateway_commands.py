"""Top-level ``gateway`` command.

Spawns the Pico gateway: agent loop + channel manager + cron service.
The bulk of the wiring lives in this command body.

``commands.py`` registers it via :func:`register`.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import typer
from loguru import logger
from rich.console import Console

from pico import __logo__
from pico.cli._helpers import (
    load_runtime_config,
    make_provider,
    print_deprecated_memory_window_notice,
)
from pico.utils.helpers import sync_workspace_templates

console = Console()


def build_model_routing(config, provider):
    """Return ``(router, provider)`` for the configured routing backend.

    - ``knn``: build a :class:`KNNModelRouter` and wrap ``provider`` in a
      :class:`PerModelProvider` so routed model names reach their endpoints
      (other models fall back to ``provider`` unchanged).
    - ``ecoclaw``: build the PinchBench :class:`ModelRouter`.
    - routing disabled, or ecoclaw with no API key: return ``(None, provider)``.
    """
    if not config.routing.enabled:
        return None, provider

    if config.routing.backend == "knn":
        from pico.providers.per_model_provider import PerModelProvider
        from pico.routing.knn_router import KNNModelRouter

        router = KNNModelRouter(config.routing, default_model=config.agents.defaults.model)
        return router, PerModelProvider(config.routing.models, fallback=provider)

    from pico.routing.router import ModelRouter

    api_key = config.routing.api_key or config.providers.openrouter.api_key or ""
    if not api_key:
        console.print("[yellow]⚠[/yellow] Routing enabled but no OpenRouter API key found — routing disabled")
        return None, provider

    from pico.routing.types import RoutingProfileName

    profile: RoutingProfileName = config.routing.profile  # type: ignore[assignment]
    router = ModelRouter(api_key=api_key, profile=profile, fallback_model=config.agents.defaults.model)
    return router, provider


_GATEWAY_IM_CHANNELS: tuple[str, ...] = (
    "feishu",
    "qq",
    "wecom",
)


def _build_gateway_channels(config) -> set[str]:
    """Build the ``allowed_channels`` set used by gateway's ``CronService`` — the
    enabled IM channels only.

    The gateway owns cron jobs for its IM channels. It does NOT claim ephemeral
    ``tui``/``cli`` jobs: those are fired by the interactive process that created
    them (the TUI / ``pico run`` session), so a TUI-set reminder always
    delivers to the TUI rather than racing the gateway and being forwarded to an
    IM channel. The trade-off is no cross-process fallback while that process is
    down; restoring "fire at origin, hand off only after the origin exits" is a
    deferred cron-delivery-ownership design, not this set.
    """
    return {name for name in _GATEWAY_IM_CHANNELS if getattr(getattr(config.channels, name, None), "enabled", False)}


async def _health_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Answer any request with a 200 ``{"status":"ok"}`` liveness body."""
    try:
        await reader.readline()
        body = b'{"status":"ok"}'
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: %d\r\nConnection: close\r\n\r\n%b" % (len(body), body)
        )
        await writer.drain()
    finally:
        writer.close()


def register(app: typer.Typer) -> None:
    """Attach the ``gateway`` command to ``app``."""

    @app.command()
    def gateway(
        port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
        config: str | None = typer.Option(None, "--config", help="Path to config file"),
    ):
        """Start the Pico gateway."""
        from pico.channels.manager import ChannelManager
        from pico.cli._runtime_assembly import assemble_runtime
        from pico.config.paths import get_cron_dir, resolve_service_paths
        from pico.config.pico import load_pico_config
        from pico.proactive_engine.schedulers.cron.service import CronService

        # load_runtime_config must run FIRST: it calls set_config_path() so
        # that subsequent load_pico_config() reads from --config, not the
        # default ~/.pico/config.json. Otherwise skill_forge from --config is
        # silently ignored.
        config = load_runtime_config(config, workspace)
        paths = resolve_service_paths(config)

        from pico.cli._log_file import redirect_loguru_to_file

        log_cfg = config.gateway.log
        log_path = redirect_loguru_to_file(
            "gateway.log",
            rotation=log_cfg.rotation,
            retention=log_cfg.retention,
            file_level="DEBUG" if verbose else log_cfg.level,
            terminal_level="DEBUG" if verbose else log_cfg.console_level,
        )

        from pico.cli._gateway_lock import GatewayAlreadyRunningError, acquire

        # Held for the whole process; closing/GC of this handle releases the lock.
        try:
            _lock_handle = acquire(now=time.time())
        except GatewayAlreadyRunningError as exc:
            since = datetime.fromtimestamp(exc.info.started_at).strftime("%Y-%m-%d %H:%M:%S")
            console.print(
                f"[red]✗[/red] Pico gateway already running for this instance "
                f"(pid {exc.info.pid}, since {since}).\n"
                f"  Stop it first, or use --config to run a separate instance."
            )
            raise typer.Exit(code=1)

        ec_config = load_pico_config()
        print_deprecated_memory_window_notice(config)
        port = port if port is not None else config.gateway.port

        console.print(f"{__logo__} Starting Pico gateway on port {port}...")
        console.print(f"[dim]📝 Logs → {log_path}[/dim]")
        sync_workspace_templates(paths.state)
        provider = make_provider(config)

        # Create cron service first (callback set after agent creation).
        #
        # Restrict to channels gateway has adapters for. This prevents the
        # gateway from racing REPL and stealing cli-origin reminders that REPL
        # can deliver but gateway can't (REPL stdout is owned by the REPL
        # process, gateway has no cli channel). Without this, you'd see
        # "Unknown channel: cli" warnings + lost REPL reminders when both
        # processes are running.
        cron_store_path = get_cron_dir() / "jobs.json"
        gateway_channels = _build_gateway_channels(config)
        cron = CronService(cron_store_path, allowed_channels=gateway_channels)

        # Create model router (and, for the knn backend, wrap the provider).
        router, provider = build_model_routing(config, provider)

        # Construct Channels before the Runtime so a broken adapter is disabled
        # (never fatal) before plugin-owned resources are claimed.
        channels = ChannelManager(config)

        runtime = assemble_runtime(
            config,
            ec_config,
            provider=provider,
            cron_service=cron,
            router=router,
            interactive=True,
            paths=paths,
        )
        agent = runtime.agent_loop
        session_manager = runtime.session_manager

        from pico.cli._cron_handler import make_on_cron_job

        if channels.enabled_channels:
            console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
        else:
            console.print("[yellow]Warning: No channels enabled[/yellow]")

        cron_status = cron.status()
        if cron_status["jobs"] > 0:
            console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

        async def run():
            health_server = None
            gw_teardown = None
            question_broker = None
            try:
                await runtime.start_memory_backend()
                # Spine assembly for the gateway's host sources (cron submits
                # through it, replies route to channels via a per-channel outlet).
                # Built here, inside the running loop, not in the sync command
                # prologue: Scheduler pins its home loop at construction (submit
                # must come from that loop), and the prologue has no loop yet.
                from pico.cli._gateway_spine import build_gateway

                gw_scheduler, gw_hub, gw_readback_texts, gw_sources, gw_teardown = build_gateway(
                    agent,
                    channels.channels,
                    user_pool=config.gateway.user_pool,
                    system_pool=config.gateway.system_pool,
                    send_max_retries=config.gateway.send_max_retries,
                )
                cron.on_job = make_on_cron_job(
                    gw_hub,
                    submit=gw_scheduler.submit,
                    readback_texts=gw_readback_texts,
                    channel_manager=channels,
                    session_manager=session_manager,
                    default_channel="cli",
                )

                # Subagent result re-injection submits a SUBAGENT-origin turn.
                agent.subagents.set_submit(gw_scheduler.submit)

                # ask_user round-trip on the channel side: the QuestionBroker
                # renders the agent's clarify.request as an outbound Text to the
                # conversation's channel; the inbound gate (below) routes the
                # user's next message back via reply(). The question fires mid-turn,
                # so the live turn's real inbound Source is still in gw_sources
                # (keyed by conversation id) — reuse it so a topic / thread address
                # is exact, rather than reconstructing it from the conversation id.
                from pico.spine import Text as _Text
                from pico.tui_rpc.question_broker import QuestionBroker

                async def _question_to_channel(frame: dict) -> None:
                    params = frame.get("params", {})
                    qcid = params.get("conversation_id", "")
                    source = gw_sources.get(qcid)
                    if source is None:
                        logger.warning(
                            "ask_user question for {} has no live source — dropping",
                            qcid,
                        )
                        return
                    body = params.get("question", "")
                    choices = params.get("choices") or []
                    if choices:
                        body += "\n" + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(choices))
                    await gw_hub.dispatch(_Text(content=body, source=source))

                question_broker = QuestionBroker(send_frame=_question_to_channel)
                if (ask_tool := agent.tools.get("ask_user")) is not None and hasattr(ask_tool, "set_broker"):
                    ask_tool.set_broker(question_broker)

                # Channel inbound runs through the spine: a permitted
                # message is submitted as a USER turn. /stop and /restart are
                # control commands (the bus drainer's job) — intercepted here, not
                # submitted as turns (else the agent would reply to the text). cid
                # matches the lane key (conversation or channel:chat_id), the same
                # session key the bus path's _handle_stop used.
                from dataclasses import replace

                from pico.spine import Text
                from pico.spine.turn import BusyPolicy

                async def _inbound_dispatch(req) -> None:
                    cmd = req.text.strip().lower()
                    cid = req.conversation or f"{req.source.channel}:{req.source.chat_id}"
                    if cmd == "/stop":
                        stopped = gw_scheduler.cancel_conversation(cid)
                        stopped += await agent.subagents.cancel_by_session(cid)
                        content = f"Stopped {stopped} task(s)." if stopped else "No active task to stop."
                        await gw_hub.dispatch(Text(content=content, source=req.source))
                    elif cmd == "/restart":
                        await gw_hub.dispatch(Text(content="Restarting...", source=req.source))

                        async def _do_restart() -> None:
                            import os
                            import sys

                            await asyncio.sleep(1)
                            os.execv(sys.executable, [sys.executable] + sys.argv)

                        asyncio.create_task(_do_restart())
                    elif question_broker.pending_req(cid) is not None:
                        # This conversation is blocked on an ask_user question —
                        # route the answer to the broker (resolving the awaiting
                        # tool) instead of starting or injecting a turn.
                        question_broker.reply(cid, req.text)
                    elif gw_scheduler.has_inflight(cid):
                        # A turn is already running this conversation — submit as
                        # BusyPolicy.INJECT so the loop merges this message at its
                        # next iteration instead of queuing a fresh turn.
                        gw_scheduler.submit(replace(req, busy=BusyPolicy.INJECT))
                    else:
                        gw_scheduler.submit(req)  # fire-and-forget (no readback)

                for _ch in channels.channels.values():
                    _ch.intake.set_submit(_inbound_dispatch)

                await cron.start()
                try:
                    health_server = await asyncio.start_server(_health_handler, "127.0.0.1", port)
                    console.print(f"[green]✓[/green] Health: http://127.0.0.1:{port}/health")
                except OSError as exc:
                    logger.warning(
                        "health endpoint unavailable on 127.0.0.1:{} ({}); gateway continues without it",
                        port,
                        exc,
                    )
                coros = [
                    agent.run(),
                    channels.start_all(),
                ]
                if health_server is not None:
                    coros.append(health_server.serve_forever())
                await asyncio.gather(*coros)
            except KeyboardInterrupt:
                console.print("\nShutting down...")
            finally:
                try:
                    if health_server is not None:
                        health_server.close()
                    # Stop background producers before tearing down the scheduler
                    # they submit through: a cron timer firing during teardown would
                    # otherwise submit to an already-shut scheduler.
                    cron.stop()
                    if question_broker is not None:
                        question_broker.cancel_all()  # release any turn blocked on ask_user
                    if gw_teardown is not None:
                        await gw_teardown()
                    agent.stop()
                    await channels.stop_all()
                finally:
                    await runtime.close()

        asyncio.run(run())


__all__ = ["register"]
