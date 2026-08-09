"""Native TUI launcher for the bare ``pico`` entry point.

Interactive launches connect the Node child to an authenticated loopback
socket and run ``RpcServer`` in an asyncio task. Diagnostic launches inherit
stdio and skip RPC.

Exit codes (in addition to bootstrap's 0/1/2):
    3  — RPC handshake timeout / failure
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Tuple

import typer

from pico.cli._log_file import _strip_tty_stream_handlers, redirect_loguru_to_file, redirect_terminal_fds_to_file
from pico.product import get_product_home

# Path to the ui-tui/ source tree, relative to this file:
# pico/cli/tui_commands.py -> ../../../ui-tui/. Only the `--dev` path (tsx from
# source) needs this; it requires src/ + node_modules and is absent from wheels.
_UI_TUI_DIR = Path(__file__).resolve().parent.parent.parent / "ui-tui"

# Packaged location of the prebuilt, self-contained bundle inside an installed
# wheel: pico/cli/tui_commands.py -> ../ui-tui/dist/entry.js (i.e.
# pico/ui-tui/dist/entry.js). pyproject force-includes ui-tui/dist here so a
# `uv tool install` ships the TUI without a source checkout.
_PACKAGED_DIST_ENTRY = Path(__file__).resolve().parent.parent / "ui-tui" / "dist" / "entry.js"

_MIN_NODE_VERSION = (22, 0, 0)


def resolve_dist_entry() -> Optional[Path]:
    """Locate the prebuilt ``entry.js`` bundle for production (non-dev) launch.

    Tries, in order:
      1. The packaged copy inside the installed wheel (``pico/ui-tui/dist``).
      2. The source-tree copy a developer built locally (``ui-tui/dist``).

    The bundle is self-contained (esbuild ``bundle: true``), so no sibling
    ``node_modules`` is needed — only a Node runtime. Returns the first path
    that exists, or ``None`` if neither does.
    """
    for candidate in (_PACKAGED_DIST_ENTRY, _UI_TUI_DIR / "dist" / "entry.js"):
        if candidate.exists():
            return candidate
    return None


def _stdout_isatty() -> bool:
    """Whether stdout is an interactive TTY (seam for the onboarding gate test;
    CliRunner swaps ``sys.stdout`` for a non-TTY buffer)."""
    return sys.stdout.isatty()


def find_node() -> Tuple[Optional[str], Optional[Tuple[int, int, int]]]:
    """Find a usable node executable (>= 22).

    Returns (path, version_tuple) or (None, None) if not found.
    """
    # Priority 1: PICO_NODE env var — explicit override, NO fallback.
    # When the user sets PICO_NODE they are forcing a specific binary;
    # if it is missing or unusable we must NOT silently fall back to
    # venv/PATH (that would mask misconfiguration).
    candidates: list[str] = []
    if env_node := os.environ.get("PICO_NODE"):
        candidates.append(env_node)
    else:
        # Priority 2: active venv
        if venv := os.environ.get("VIRTUAL_ENV"):
            if sys.platform == "win32":
                candidates.append(str(Path(venv) / "Scripts" / "node.exe"))
            else:
                candidates.append(str(Path(venv) / "bin" / "node"))

        # Priority 3: PATH
        if path_node := shutil.which("node"):
            candidates.append(path_node)

        # Priority 4: Pico-managed private runtime installed by the one-line
        # installer into ~/.pico/runtime/. This is the zero-config fallback so
        # a user who has no system Node still gets a working `pico` after
        # the installer provisioned a private Node here. Glob to tolerate the
        # versioned dir name. The on-disk layout differs by OS: POSIX tarballs
        # nest the binary under bin/ (node-v22.x.y-darwin-arm64/bin/node) while
        # the Windows zip puts node.exe at the top level
        # (node-v22.x.y-win-x64/node.exe) — install.ps1 provisions the latter.
        runtime_root = get_product_home() / "runtime"
        if runtime_root.is_dir():
            if sys.platform == "win32":
                direct = runtime_root / "node" / "node.exe"
                if direct.exists():
                    candidates.append(str(direct))
                candidates.extend(str(p) for p in sorted(runtime_root.glob("node-*/node.exe")))
            else:
                direct = runtime_root / "node" / "bin" / "node"
                if direct.exists():
                    candidates.append(str(direct))
                candidates.extend(str(p) for p in sorted(runtime_root.glob("node-*/bin/node")))

    for node_path in candidates:
        if not Path(node_path).exists():
            continue
        try:
            proc = subprocess.run(
                [node_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            match = re.match(r"v(\d+)\.(\d+)\.(\d+)", proc.stdout.strip())
            if not match:
                continue
            version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return (node_path, version)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue

    return (None, None)


def run_subprocess(
    node_path: str,
    args: list[str],
    cwd: Path,
    forward_signals: bool = True,
) -> int:
    """Spawn node subprocess, inherit stdio, forward signals, return exit code."""
    proc = subprocess.Popen(
        [node_path, *args],
        cwd=str(cwd),
        stdin=None,
        stdout=None,
        stderr=None,
    )

    if forward_signals:

        def _forward(sig, _frame):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                pass

        signal.signal(signal.SIGINT, _forward)
        signal.signal(signal.SIGTERM, _forward)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _forward)

    try:
        return proc.wait()
    except KeyboardInterrupt:
        # Already forwarded above; wait briefly for graceful exit.
        try:
            return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            return proc.wait()


# ---------------------------------------------------------------------------
# RPC handshake + asyncio server loop
# ---------------------------------------------------------------------------

# Handshake budget: spec 5.1 — Node must send `system.hello` within 5 s of
# spawn or the parent aborts with exit 3.
_RPC_HANDSHAKE_TIMEOUT_S: float = 5.0
_RPC_HANDSHAKE_EXIT_CODE: int = 3

# The Node child connects to the TCP loopback address exported in
# PICO_RPC_SOCKET and authenticates with the PICO_RPC_TOKEN shared secret.
# Loopback is reachable by any local process, so the token preserves the trust
# boundary before the server dispatches any request.
_RPC_SOCKET_ENV: str = "PICO_RPC_SOCKET"
_RPC_TOKEN_ENV: str = "PICO_RPC_TOKEN"  # noqa: S105 -- env var name, not a secret


def _suppress_noisy_watchers() -> None:
    """Raise file-watcher loggers to INFO so ``watchfiles`` per-poll DEBUG
    chatter ('rust notify timeout') stays out of the log sink."""
    import logging as _stdlib_logging

    for _name in ("watchfiles", "watchfiles.main", "watchfiles.watcher", "watchdog", "notify"):
        _stdlib_logging.getLogger(_name).setLevel(_stdlib_logging.INFO)


def _drop_watcher_spam(record: dict) -> bool:
    """Sink filter dropping watchfiles poll-timeout chatter (TUI-only, so the
    shared gateway sink is unaffected)."""
    return "rust notify timeout" not in record["message"]


# Narrow exception classes that represent recoverable init-time crashes —
# kwargs drift after AgentLoop ctor refactor, attribute path drift after
# config schema rename, ImportError on optional extras, missing config file,
# Pydantic ValidationError. All are surfaced as -32603 ``internal_error``
# with ``data.reason="tui_init_crash"`` so the UI can distinguish them from a
# legitimate -32008 ``model_not_available`` (no provider configured).
_TUI_INIT_CRASH_TYPES: tuple[type[BaseException], ...] = (
    TypeError,
    AttributeError,
    ImportError,
    FileNotFoundError,
    OSError,
)


async def _fanout_cron_delivered(emitter, *, job_id, name, text, fired_at) -> None:
    """Fan a ``cron.delivered`` event out to every active TUI session.

    Fan-out (rather than a session-keyed emit) is required because a cron turn
    runs in the ``cron:<job_id>`` conversation, which matches no user
    subscription key. TUI v0.1 is single-session per ``hermes-tui-rpc-architecture``
    5-domain fallback.
    """
    payload = {"job_id": job_id, "name": name, "text": text, "fired_at": fired_at}
    for session_key in list(emitter._by_session.keys()):
        await emitter.emit(session_key, {"type": "cron.delivered", "payload": payload})


def _build_cron_callback_spine(base_on_cron, emitter):
    """Wrap the spine cron callback so a delivering job's reply is fanned out as a
    ``cron.delivered`` event. ``base_on_cron`` (``make_on_cron_job`` with
    ``submit=``) runs the reminder as a CRON turn through the TUI scheduler and
    returns its reply (read back from the runner via ``readback_texts``); the cron
    turn's own hub deliverables target the ``cron:<job_id>`` conversation, which
    has no subscriber and so no-op, making this fan-out the only delivery path."""
    from datetime import datetime, timezone

    async def wrapped(job):
        response = await base_on_cron(job)
        if job.payload.deliver and response:
            await _fanout_cron_delivered(
                emitter,
                job_id=job.id,
                name=job.name,
                text=response,
                fired_at=datetime.now(timezone.utc).isoformat(),
            )
        return response

    return wrapped


def _build_tui_runtime():
    """Construct the Runtime served by ``turn.send``.

    Wires a TUI-scoped ``CronService(allowed_channels={"tui"})`` so the
    Runtime can register reminders from within a TUI turn. The provider remains
    lazy, and Cron delivery plus TUI interaction policy stay in this host.

    Raises ``InternalError`` (-32603) when AgentLoop construction fails —
    ``_run_rpc_server_until_done`` catches and latches the error onto the
    factory closure passed to ``register_aligned_methods_except_system`` so
    ``turn.send`` can emit it through the subscription emitter (the launcher
    has no live client connection at startup time).
    """
    from pydantic import ValidationError

    from pico.plugin.registry import PluginNotFoundError
    from pico.tui_rpc.errors import InternalError

    try:
        from pico.cli._helpers import load_runtime_config, make_lazy_provider
        from pico.cli._runtime_assembly import assemble_runtime
        from pico.config.paths import get_cron_dir, resolve_foreground_paths
        from pico.config.pico import load_pico_config
        from pico.proactive_engine.schedulers.cron.service import CronService
        from pico.proactive_engine.schedulers.cron.tool import CronTool
        from pico.utils.helpers import sync_workspace_templates

        config = load_runtime_config(None, None)
        paths = resolve_foreground_paths(config)
        ec_config = load_pico_config()
        sync_workspace_templates(paths.state, silent=True)

        provider = make_lazy_provider(config)

        cron = CronService(
            get_cron_dir() / "jobs.json",
            allowed_channels={"tui"},
        )

        runtime = assemble_runtime(
            config,
            ec_config,
            provider=provider,
            cron_service=cron,
            interactive=True,
            paths=paths,
        )
        agent_loop = runtime.agent_loop

        registered_cron_tool = agent_loop.tools.get("cron")
        if isinstance(registered_cron_tool, CronTool):
            registered_cron_tool.set_context("tui", "default")

        # cron.on_job is wired in _run_rpc_server_until_done once the spine
        # scheduler exists: a reminder runs as a CRON turn through the
        # scheduler and its reply is fanned out as a cron.delivered event.

        return runtime
    except PluginNotFoundError as e:
        from loguru import logger as _logger

        _logger.exception(
            "tui: plugin configuration failed; surfacing actionable internal_error",
        )
        raise InternalError(
            detail=str(e),
            data={
                "reason": "plugin_configuration_error",
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "log_path": "~/.pico/logs/tui.log",
                "public_message": str(e),
            },
        ) from e
    except (*_TUI_INIT_CRASH_TYPES, ValidationError) as e:
        from loguru import logger as _logger

        _logger.exception(
            "tui: _build_tui_runtime init crash ({}); surfacing as -32603 internal_error",
            type(e).__name__,
        )
        raise InternalError(
            detail=str(e),
            data={
                "reason": "tui_init_crash",
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "log_path": "~/.pico/logs/tui.log",
            },
        ) from e
    except Exception as e:
        from loguru import logger as _logger

        _logger.exception(
            "tui: _build_tui_runtime uncaught exception; surfacing as -32603 internal_error",
        )
        raise InternalError(
            detail=str(e),
            data={
                "reason": "uncaught",
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "log_path": "~/.pico/logs/tui.log",
            },
        ) from e


def _build_tui_agent_loop():
    """Compatibility seam for tests and callers that only need the Agent Loop."""
    return _build_tui_runtime().agent_loop


async def _run_rpc_server_until_done(
    conn: socket.socket,
    auth_token: str,
    handshake_deadline_s: float,
    proc_done: asyncio.Event,
) -> bool:
    """Run RpcServer until the child exits or we abort on handshake timeout.

    Returns True if handshake succeeded (system.hello was received within the
    deadline); False if it timed out.
    """
    # Lazy import: keeps tui_commands importable without pulling tui_rpc on
    # users who never touch the TUI (e.g. CLI-only workflows).
    from pico.tui_rpc.confirm_broker import ConfirmBroker
    from pico.tui_rpc.dispatcher import Dispatcher
    from pico.tui_rpc.methods import register_aligned_methods_except_system
    from pico.tui_rpc.methods.system import (
        system_hello as _orig_hello,
    )
    from pico.tui_rpc.methods.system import (
        system_ping,
        system_version,
    )
    from pico.tui_rpc.question_broker import QuestionBroker
    from pico.tui_rpc.server import RpcServer
    from pico.tui_rpc.spine import build_tui
    from pico.tui_rpc.subscriptions import SubscriptionEmitter

    handshake_done = asyncio.Event()

    async def hello_then_signal(params: dict) -> dict:
        result = await _orig_hello(params)
        handshake_done.set()
        return result

    dispatcher = Dispatcher()
    # Server is constructed before umbrella registration so the
    # SubscriptionEmitter can bind its send_frame method as the notification
    # sink. serve_forever() is still started LAST (after all handlers are
    # registered) — RpcServer.send_frame raises until serve_forever has set
    # up the write transport, but emitter only emits after a subscribe call,
    # which can only happen post-handshake / post-serve.
    server = RpcServer(dispatcher=dispatcher, sock=conn, auth_token=auth_token)
    emitter = SubscriptionEmitter(send_frame=server.send_frame)
    # ConfirmBroker shares the same send_frame sink so runtime confirmations
    # can emit confirm.request and await confirm.respond. cancel_all() in the
    # finally block resolves pending confirmations when the connection drops.
    confirm_broker = ConfirmBroker(send_frame=server.send_frame)
    # QuestionBroker shares the same send_frame sink: the ask_user tool emits a
    # clarify.request and awaits clarify.respond, mirroring ConfirmBroker.
    question_broker = QuestionBroker(send_frame=server.send_frame)

    from pico.cli._runtime_host import TuiRuntimeHost
    from pico.tui_rpc.errors import InternalError, RpcError

    agent_loop = None
    build_error: RpcError | None = None
    runtime_host = TuiRuntimeHost(_build_tui_runtime)

    def _agent_loop_factory():
        if agent_loop is not None:
            return agent_loop
        if build_error is not None:
            raise build_error
        return None

    turn_scheduler = None
    turn_ids: dict[int, str] = {}
    submission_ids: dict[int, str] = {}
    turn_teardown = None
    serve_task: asyncio.Task | None = None
    runtime_bind_task: asyncio.Task | None = None
    runtime_services_task: asyncio.Task | None = None
    runtime_bound = asyncio.Event()
    backend_ready = asyncio.Event()
    backend_start_error: InternalError | None = None
    cleanup_done = False

    async def _bind_runtime() -> None:
        nonlocal agent_loop, build_error, turn_scheduler, turn_teardown
        try:
            runtime = await runtime_host.acquire()
            agent_loop = runtime.agent_loop
            if (ask_tool := agent_loop.tools.get("ask_user")) is not None and hasattr(ask_tool, "set_broker"):
                ask_tool.set_broker(question_broker)

            from types import SimpleNamespace

            from pico.cli._cron_handler import make_on_cron_job
            from pico.tui_rpc.methods import turn as turn_module

            cron_readback: dict[str, str] = {}
            turn_scheduler, turn_hub, _, _, turn_teardown = build_tui(
                agent_loop,
                emitter,
                on_turn_end=turn_module.clear_active,
                readback_texts=cron_readback,
                await_runtime_ready=_await_runtime_ready,
                turn_ids=turn_ids,
                submission_ids=submission_ids,
            )
            agent_loop.subagents.set_submit(turn_scheduler.submit)
            if agent_loop.cron_service is not None:
                base_on_cron = make_on_cron_job(
                    turn_hub,
                    submit=turn_scheduler.submit,
                    readback_texts=cron_readback,
                    channel_manager=SimpleNamespace(enabled_channels=["tui"]),
                    default_channel="tui",
                )
                agent_loop.cron_service.on_job = _build_cron_callback_spine(base_on_cron, emitter)
        except RpcError as exc:
            build_error = exc
        except Exception as exc:
            build_error = InternalError(
                detail="runtime binding failed",
                data={"reason": "runtime_binding_failed"},
            )
            from loguru import logger as _logger

            _logger.exception("tui: runtime binding failed: {}", type(exc).__name__)
        finally:
            runtime_bound.set()

    async def _acquire_turn_scheduler():
        await runtime_bound.wait()
        if build_error is not None:
            raise build_error
        if turn_scheduler is None:
            raise InternalError(
                detail="runtime scheduler unavailable",
                data={"reason": "runtime_scheduler_unavailable"},
            )
        return turn_scheduler

    async def _start_runtime_services() -> None:
        nonlocal backend_start_error
        try:
            await handshake_done.wait()
            await runtime_bound.wait()
            if build_error is not None:
                return
            runtime = runtime_host.get_now()
            if runtime is None or agent_loop is None:
                return
            await runtime.start_memory_backend()
            _strip_tty_stream_handlers()
            if agent_loop.cron_service is not None:
                await agent_loop.cron_service.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            backend_start_error = InternalError(
                detail="runtime services failed to start",
                data={"reason": "runtime_start_failed"},
            )
            from loguru import logger as _logger

            _logger.exception("tui: runtime service startup failed")
        finally:
            backend_ready.set()

    async def _await_runtime_ready() -> None:
        await backend_ready.wait()
        if backend_start_error is not None:
            raise backend_start_error

    async def _cleanup() -> None:
        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True
        if serve_task is not None:
            serve_task.cancel()
            try:
                await serve_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            confirm_broker.cancel_all()
        except Exception:
            pass
        try:
            question_broker.cancel_all()
        except Exception:
            pass
        if runtime_services_task is not None:
            if not runtime_services_task.done():
                runtime_services_task.cancel()
            try:
                await runtime_services_task
            except (asyncio.CancelledError, Exception):
                pass
        if runtime_bind_task is not None:
            try:
                await runtime_bind_task
            except (asyncio.CancelledError, Exception):
                pass
        if agent_loop is not None and agent_loop.cron_service is not None:
            try:
                agent_loop.cron_service.stop()
            except Exception:
                pass
        if turn_teardown is not None:
            try:
                await turn_teardown()
            except Exception:
                pass
        await runtime_host.close()

    try:
        # Wrap system.hello to latch the handshake event; the umbrella below
        # registers the retained conversational RPC surface.
        dispatcher.register("system.hello", hello_then_signal)
        dispatcher.register("system.ping", system_ping)
        dispatcher.register("system.version", system_version)
        register_aligned_methods_except_system(
            dispatcher,
            emitter=emitter,
            agent_loop_factory=_agent_loop_factory,
            confirm_broker=confirm_broker,
            question_broker=question_broker,
            scheduler_factory=_acquire_turn_scheduler,
            turn_ids=turn_ids,
            submission_ids=submission_ids,
        )

        from pico.config.paths import get_logs_dir

        # The child already inherited the terminal. Keep Runtime startup and
        # teardown inside this redirect so backend logging cannot corrupt it.
        with redirect_terminal_fds_to_file(get_logs_dir() / "tui.log"):
            _strip_tty_stream_handlers()
            serve_task = asyncio.create_task(server.serve_forever())
            runtime_bind_task = asyncio.create_task(_bind_runtime())
            runtime_services_task = asyncio.create_task(_start_runtime_services())

            try:
                # Wait until EITHER handshake completes OR deadline expires OR child exits.
                done, pending = await asyncio.wait(
                    {
                        asyncio.create_task(handshake_done.wait()),
                        asyncio.create_task(proc_done.wait()),
                    },
                    timeout=handshake_deadline_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                # Drain cancelled tasks to suppress warnings.
                for t in pending:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

                if not handshake_done.is_set():
                    return False
                # Continue serving until child exits.
                await proc_done.wait()
                return True
            finally:
                await _cleanup()
    finally:
        await _cleanup()


def _spawn_with_rpc_socket(
    node_path: str,
    args: list[str],
    cwd: Path,
) -> tuple[subprocess.Popen[bytes], socket.socket, str]:
    """Spawn `[node_path, *args]` with a per-session TCP-loopback socket.

    Topology (cross-platform: macOS / Linux / Windows):

        parent: socket()/bind()/listen() on 127.0.0.1:<ephemeral>; exports the
                ``host:port`` as ``PICO_RPC_SOCKET`` and a random shared secret
                as ``PICO_RPC_TOKEN``
        child:  reads ``PICO_RPC_SOCKET``, ``net.createConnection({host,port})``,
                sends ``PICO_RPC_TOKEN`` as the first line, then emits JSON-RPC
                frames + reads responses on the same socket

    Loopback (127.0.0.1) is reachable by any local process, so the token --
    known only to the child we spawn (passed via env) -- is what keeps a rogue
    local process from talking to us; the parent validates it as the first line
    (see ``RpcServer(auth_token=...)``) before any dispatch.

    Returns ``(popen, listening_server_socket, auth_token)``. Caller must
    eventually ``server_sock.close()``. The accepted client connection is NOT
    created here -- that's done by :func:`_run_rpc_server_until_done` once the
    asyncio loop is up so the accept can be cancelled cleanly on handshake
    timeout.
    """
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    host, port = server_sock.getsockname()[:2]

    token = secrets.token_hex(32)
    env = os.environ.copy()
    env[_RPC_SOCKET_ENV] = f"{host}:{port}"
    env[_RPC_TOKEN_ENV] = token

    proc = subprocess.Popen(
        [node_path, *args],
        cwd=str(cwd),
        stdin=None,
        stdout=None,
        stderr=None,
        env=env,
    )

    return proc, server_sock, token


async def _accept_with_timeout(
    server_sock: socket.socket,
    timeout_s: float,
) -> socket.socket | None:
    """Accept one connection on `server_sock` or return None on timeout.

    Uses ``loop.sock_accept`` so the wait is cooperatively cancellable.
    """
    server_sock.setblocking(False)
    loop = asyncio.get_running_loop()
    try:
        conn, _addr = await asyncio.wait_for(loop.sock_accept(server_sock), timeout=timeout_s)
    except asyncio.TimeoutError:
        return None
    conn.setblocking(False)
    return conn


def run_subprocess_with_rpc(
    node_path: str,
    args: list[str],
    cwd: Path,
    forward_signals: bool = True,
) -> int:
    """Spawn Node child with a per-session TCP-loopback socket; run RpcServer; enforce handshake.

    Cross-platform transport (macOS / Linux / Windows): the parent listens on
    ``127.0.0.1:<ephemeral>`` and exports the ``host:port`` via
    ``PICO_RPC_SOCKET`` plus a random shared secret via ``PICO_RPC_TOKEN``.
    The Node child connects, sends the token as the first newline-terminated
    line, then speaks newline-JSON frames. The accepted socket *object* is
    handed to ``RpcServer`` (no os.dup of a socket fd -- unsupported on
    Windows), which wires it via ``loop.connect_accepted_socket`` and validates
    the token before any dispatch.

    Returns the child's exit code, OR ``_RPC_HANDSHAKE_EXIT_CODE`` (3) if
    the handshake times out (either because the child never connected, or
    because it connected but never sent the token + ``system.hello``).
    """
    proc, server_sock, auth_token = _spawn_with_rpc_socket(node_path, args, cwd)

    if forward_signals:

        def _forward(sig, _frame):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                pass

        signal.signal(signal.SIGINT, _forward)
        signal.signal(signal.SIGTERM, _forward)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _forward)

    proc_done = asyncio.Event()

    def _waiter() -> None:
        try:
            proc.wait()
        finally:
            try:
                loop = _loop_holder.get("loop")
                if loop is not None and not loop.is_closed():
                    loop.call_soon_threadsafe(proc_done.set)
            except RuntimeError:
                pass

    _loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

    _conn_holder: dict[str, socket.socket] = {}
    _flags = {"handed_off": False}

    async def _main() -> bool:
        _loop_holder["loop"] = asyncio.get_running_loop()

        # Wait for child to connect within the handshake deadline. We race
        # `accept` against `proc.wait()` so an early-exiting child returns
        # immediately instead of stalling for the full 5 s.
        accept_task = asyncio.create_task(_accept_with_timeout(server_sock, _RPC_HANDSHAKE_TIMEOUT_S))
        proc_done_task = asyncio.create_task(proc_done.wait())
        done, pending = await asyncio.wait(
            {accept_task, proc_done_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=_RPC_HANDSHAKE_TIMEOUT_S,
        )
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        if accept_task not in done:
            return False
        conn = accept_task.result()
        if conn is None:
            return False
        _conn_holder["conn"] = conn

        # Hand the connected socket object straight to RpcServer. We do NOT
        # os.dup the fd (unsupported on Windows) — connect_accepted_socket takes
        # ownership of this one socket and closes it on teardown, so the outer
        # cleanup must not double-close it.
        _flags["handed_off"] = True
        return await _run_rpc_server_until_done(conn, auth_token, _RPC_HANDSHAKE_TIMEOUT_S, proc_done)

    waiter = threading.Thread(target=_waiter, daemon=True)
    waiter.start()

    handshake_ok = False
    try:
        handshake_ok = asyncio.run(_main())
    finally:
        # 1) Close the accepted conn only if it was never handed to RpcServer.
        # Once handed off, the server owns it (connect_accepted_socket) and
        # closes it on teardown; double-closing here would race that.
        if "conn" in _conn_holder and not _flags["handed_off"]:
            try:
                _conn_holder["conn"].close()
            except OSError:
                pass
        # 2) Close the listening socket.
        try:
            server_sock.close()
        except OSError:
            pass

    if not handshake_ok:
        print(
            f"✗ RPC handshake timeout ({_RPC_HANDSHAKE_TIMEOUT_S:.0f}s); is the Node side using the new IPC bridge?",
            file=sys.stderr,
        )
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        return _RPC_HANDSHAKE_EXIT_CODE

    waiter.join(timeout=5)
    return proc.returncode if proc.returncode is not None else 0


def _print_node_help(out=None) -> None:
    """Print the friendly Node-missing error message."""
    msg = (
        "✗ TUI 启动失败：未找到 Node.js ≥ 22。\n"
        "  安装：https://nodejs.org/  或  brew install node@22  或  nvm install 22\n"
        "  或：临时使用行式 REPL  ->  pico run --legacy-repl\n"
    )
    typer.echo(msg, file=out)


def _is_abnormal_child_exit(exit_code: int) -> bool:
    """A child exit worth surfacing to the user: not a clean exit, not one of
    the signals the parent forwards for a graceful shutdown, and not the
    RPC-handshake failure path (which reports itself).

    The graceful signal codes mirror ui-tui gracefulExit.ts, which maps SIGHUP
    to 129 (terminal closed), SIGINT to 130 (Ctrl+C) and SIGTERM to 143
    (kill / process manager) through one clean-exit path. A hard SIGKILL (137)
    is left abnormal. ``_RPC_HANDSHAKE_EXIT_CODE`` is 3."""
    return exit_code not in (0, 129, 130, 143, _RPC_HANDSHAKE_EXIT_CODE)


def launch_tui(
    *,
    check: bool = False,
    dev: bool = False,
    color: Optional[str] = None,
    print_colors: bool = False,
    preview_colors: bool = False,
) -> None:
    """Launch Pico native TUI."""
    # Startup gate: launch the onboarding wizard first when the required
    # config (a provider key + default model) is missing. Skipped for the
    # no-TTY diagnostic spawns (--check / --print-colors / --preview-colors).
    if not (check or print_colors or preview_colors) and _stdout_isatty():
        from pico.cli.onboard_commands import (
            _is_config_populated,
            ensure_configured_or_onboard,
        )

        if not _is_config_populated():
            ensure_configured_or_onboard()

    node_path, version = find_node()
    if node_path is None:
        _print_node_help()
        raise typer.Exit(code=1)
    if version is None or version < _MIN_NODE_VERSION:
        ver_str = ".".join(map(str, version)) if version else "<unknown>"
        typer.echo(
            f"✗ Node 版本过低（找到 {ver_str}，需要 >= 22）。\n  请升级：nvm install 22  或  brew upgrade node\n",
        )
        raise typer.Exit(code=1)

    # `--dev` runs tsx from the source tree, so it requires the ui-tui/ checkout.
    # The production path resolves a packaged or source-built bundle separately
    # (see resolve_dist_entry), so it must NOT hard-require the source tree —
    # a wheel install legitimately has no ui-tui/ source directory.
    if dev and not _UI_TUI_DIR.exists():
        print(f"✗ TUI 源码缺失（--dev 需要源码树）：{_UI_TUI_DIR}", file=sys.stderr)
        raise typer.Exit(code=2)

    # Color override flows to the child via env (entry.tsx -> colorTier.ts).
    # Only set it when --color was passed so a shell-level PICO_TUI_COLOR
    # isn't clobbered by the "auto" default.
    if color is not None:
        os.environ["PICO_TUI_COLOR"] = color

    # `--check` is a smoke test: tell the child to boot, prove runtime init,
    # then exit 0 (no Ink render, no interactive TTY). The child reads
    # PICO_TUI_CHECK from the environment it inherits from this process.
    # See ui-tui/src/entry.tsx for the matching handler.
    if check:
        os.environ["PICO_TUI_CHECK"] = "1"

    # `--print-colors` / `--preview-colors` are no-IPC diagnostics: the child
    # dumps the resolved palette (swatches / in-context) and exits. Like
    # --check they skip the RPC handshake.
    if print_colors:
        os.environ["PICO_TUI_PRINT_COLORS"] = "1"
    if preview_colors:
        os.environ["PICO_TUI_COLOR_PREVIEW"] = "1"

    # --check / --print-colors / --preview-colors are no-RPC, stdio-only spawns.
    no_rpc = check or print_colors or preview_colors

    # Redirect parent loguru to a file so RPC server logs
    # logs don't corrupt the Ink reconciler. (Skipped for the no-RPC paths
    # which exit before Ink renders.) The file is created here at startup and
    # a normal run/exit only writes INFO lifecycle records, so the path is
    # surfaced to the user only on an abnormal child exit (see below).
    if not no_rpc:
        _suppress_noisy_watchers()
        log_path = redirect_loguru_to_file(
            "tui.log",
            retention=3,
            record_filter=_drop_watcher_spam,
        )

    if dev:
        # tsx watch via local node_modules.
        # Derive npx from the validated node_path so PICO_NODE's
        # version-pin semantics are honored end-to-end. Only fall back to
        # PATH when the derived path is absent (rare; e.g. operator points
        # PICO_NODE at a standalone node binary with no sibling npx).
        derived_npx = Path(node_path).parent / "npx"
        if derived_npx.exists():
            npx = str(derived_npx)
        else:
            fallback = shutil.which("npx")
            if fallback is not None and os.environ.get("PICO_NODE"):
                typer.echo(
                    f"⚠ PICO_NODE was set but no `npx` next to {node_path};\n"
                    f"  falling back to PATH npx at {fallback}. Node version\n"
                    f"  used by tsx may differ from the validated one.\n",
                    err=True,
                )
            npx = fallback or "npx"
        # Use npx to run tsx (source mode, no build step); npx ships with
        # node >= 22. `--watch` is intentionally dropped: the interactive path
        # requires a one-shot RPC handshake (parent accepts a
        # single socket connection), and a watch-triggered restart would drop
        # that connection. --check stays on the plain spawn because entry.tsx
        # short-circuits on PICO_TUI_CHECK before the socket guard, so it
        # needs no RPC server; the interactive path must open the socket or
        # entry.tsx exits 2 ("PICO_RPC_SOCKET env var required").
        tsx_args = ["tsx", "src/entry.tsx"]
        if no_rpc:
            exit_code = run_subprocess(npx, tsx_args, cwd=_UI_TUI_DIR)
        else:
            exit_code = run_subprocess_with_rpc(npx, tsx_args, cwd=_UI_TUI_DIR)
    else:
        dist_entry = resolve_dist_entry()
        if dist_entry is None:
            print(
                f"✗ TUI 构建产物缺失：{_PACKAGED_DIST_ENTRY}（或源码树 {_UI_TUI_DIR / 'dist' / 'entry.js'}）\n"
                f"  开发者请运行：cd {_UI_TUI_DIR} && npm install && npm run build\n"
                "  用户请从 Pico 仓库重新运行安装脚本。\n",
                file=sys.stderr,
            )
            raise typer.Exit(code=2)
        # The self-contained bundle needs no node_modules; run it from its own
        # directory so any relative resource resolution stays well-defined.
        dist_cwd = dist_entry.parent
        # `--check` smoke path keeps the simple stdio-only spawn so the
        # bootstrap-era tests (which don't speak JSON-RPC) still pass; the
        # interactive run path opens the RPC socket and enforces handshake.
        if no_rpc:
            exit_code = run_subprocess(node_path, [str(dist_entry)], cwd=dist_cwd)
        else:
            exit_code = run_subprocess_with_rpc(node_path, [str(dist_entry)], cwd=dist_cwd)

    # tui.log stays silent on a clean run; surface it only when the child
    # exited abnormally (see _is_abnormal_child_exit).
    if not no_rpc and _is_abnormal_child_exit(exit_code):
        typer.echo(f"📝 TUI logs → {log_path} (exit {exit_code})", err=True)

    raise typer.Exit(code=exit_code)
