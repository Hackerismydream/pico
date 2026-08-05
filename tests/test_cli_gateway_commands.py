"""CLI tests for ``pico gateway``.

The ``gateway`` command spawns the agent loop, channel manager, cron service,
and optional background services, then runs forever. Smoke-level coverage only:
``--help`` works, options are surfaced, and the no-API-key path exits cleanly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pico.cli.commands import app
from pico.config.loader import set_config_path

runner = CliRunner()


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.json"
    set_config_path(cfg)
    yield cfg
    set_config_path(None)  # type: ignore[arg-type]


def test_gateway_help_works() -> None:
    """``pico gateway --help`` lists the documented options."""
    r = runner.invoke(app, ["gateway", "--help"])
    assert r.exit_code == 0
    assert "Start the Pico gateway" in r.stdout
    assert "--port" in r.stdout
    assert "--workspace" in r.stdout
    assert "--verbose" in r.stdout
    assert "--config" in r.stdout


def test_gateway_config_short_alias_removed() -> None:
    """``-c`` no longer binds ``--config`` (UN-41); only the long form remains."""
    bad = runner.invoke(app, ["gateway", "-c", "/tmp/whatever.json"])
    assert bad.exit_code != 0

    r = runner.invoke(app, ["gateway", "--help"])
    assert r.exit_code == 0
    assert "--config" in r.stdout


def test_gateway_without_api_key_exits_with_error(tmp_config: Path) -> None:
    """With no provider configured, gateway must exit non-zero — and crucially
    must not raise a crash-class exception (NameError / AttributeError /
    ImportError). Those would indicate a regression like a missing import.
    """
    from pico.config.loader import save_config
    from pico.config.schema import Config

    save_config(Config())  # default config, no keys

    r = runner.invoke(app, ["gateway"])
    if r.exception is not None:
        assert not isinstance(r.exception, (NameError, AttributeError, ImportError)), (
            f"Crash-class exception leaked through: {r.exception!r}"
        )
    assert r.exit_code != 0


@pytest.mark.parametrize("channel_validation_fails", [False, True])
def test_gateway_validates_channels_before_shared_runtime_assembly(
    tmp_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    channel_validation_fails: bool,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from pico.cli import _runtime_assembly, gateway_commands
    from pico.config.paths import RuntimePaths

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = MagicMock()
    config.workspace_path = workspace
    config.gateway.port = 18_790
    config.gateway.log = SimpleNamespace(
        rotation="10 MB",
        retention=7,
        level="INFO",
        console_level="INFO",
    )
    for name in ("feishu", "qq", "wecom"):
        getattr(config.channels, name).enabled = False
    pico_config = MagicMock()
    provider = object()
    router = object()
    cron_service = MagicMock()
    cron_service.status.return_value = {"jobs": 0}
    runtime = SimpleNamespace(
        agent_loop=MagicMock(),
        session_manager=object(),
    )
    calls: list[tuple[tuple, dict]] = []

    monkeypatch.setattr(
        gateway_commands,
        "load_runtime_config",
        lambda config_path, workspace_path: config,
    )
    monkeypatch.setattr(gateway_commands, "make_provider", lambda cfg: provider)
    monkeypatch.setattr(
        gateway_commands,
        "print_deprecated_memory_window_notice",
        lambda cfg: None,
    )
    monkeypatch.setattr(
        gateway_commands,
        "sync_workspace_templates",
        lambda workspace_path: None,
    )
    monkeypatch.setattr(
        "pico.cli._log_file.redirect_loguru_to_file",
        lambda *args, **kwargs: tmp_path / "gateway.log",
    )
    monkeypatch.setattr(
        "pico.cli._gateway_lock.acquire",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        "pico.config.pico.load_pico_config",
        lambda: pico_config,
    )
    monkeypatch.setattr(
        "pico.config.paths.get_cron_dir",
        lambda: tmp_path / "cron",
    )
    monkeypatch.setattr(
        "pico.proactive_engine.schedulers.cron.service.CronService",
        lambda *args, **kwargs: cron_service,
    )
    monkeypatch.setattr(
        gateway_commands,
        "build_model_routing",
        lambda cfg, initial_provider: (router, initial_provider),
    )

    def _assemble(*args, **kwargs):
        calls.append((args, kwargs))
        return runtime

    monkeypatch.setattr(_runtime_assembly, "assemble_runtime", _assemble)

    class _ChannelValidationFailure(RuntimeError):
        pass

    class _StopAfterAssembly(RuntimeError):
        pass

    channels = SimpleNamespace(enabled_channels=[], channels={})

    def _build_channels(cfg):
        if channel_validation_fails:
            raise _ChannelValidationFailure
        return channels

    monkeypatch.setattr(
        "pico.channels.manager.ChannelManager",
        _build_channels,
    )

    def _stop_async_run(coro):
        coro.close()
        raise _StopAfterAssembly

    monkeypatch.setattr(gateway_commands.asyncio, "run", _stop_async_run)

    result = runner.invoke(
        app,
        ["gateway", "--config", str(tmp_config)],
    )

    expected_exception = _ChannelValidationFailure if channel_validation_fails else _StopAfterAssembly
    assert isinstance(result.exception, expected_exception)
    assert len(calls) == (0 if channel_validation_fails else 1)
    if channel_validation_fails:
        return
    assert calls[0][0] == (config, pico_config)
    assert calls[0][1] == {
        "provider": provider,
        "cron_service": cron_service,
        "router": router,
        "interactive": True,
        "paths": RuntimePaths(
            workspace=config.workspace_path,
            state=config.workspace_path,
        ),
    }


def test_gateway_refuses_second_instance(tmp_config: Path, monkeypatch) -> None:
    """When the instance lock is already held, gateway exits 1 with a clear
    message and never builds the agent/channel stack."""
    from pico.config.loader import save_config
    from pico.config.schema import Config

    save_config(Config())

    from pico.cli import _gateway_lock

    def _raise(now: float):
        raise _gateway_lock.GatewayAlreadyRunningError(
            _gateway_lock.LockInfo(pid=4242, started_at=0.0, config_path=str(tmp_config))
        )

    monkeypatch.setattr(_gateway_lock, "acquire", _raise)

    r = runner.invoke(app, ["gateway"])
    assert r.exit_code == 1
    assert "already running for this instance" in r.stdout
    assert "4242" in r.stdout


def test_gateway_log_config_defaults() -> None:
    from pico.config.schema import GatewayConfig

    cfg = GatewayConfig()
    log = cfg.log
    assert not hasattr(cfg, "heartbeat")
    assert log.rotation == "10 MB"
    assert log.retention == 7
    assert log.level == "INFO"
    assert log.console_level == "INFO"


def test_gateway_log_config_overrides_parse() -> None:
    from pico.config.schema import GatewayConfig

    cfg = GatewayConfig.model_validate(
        {
            "log": {
                "rotation": "00:00",
                "retention": "14 days",
                "level": "DEBUG",
                "console_level": "WARNING",
            }
        }
    )
    assert cfg.log.rotation == "00:00"
    assert cfg.log.retention == "14 days"
    assert cfg.log.level == "DEBUG"
    assert cfg.log.console_level == "WARNING"


def test_gateway_channels_excludes_tui_when_no_im_enabled() -> None:
    # The gateway does not claim ephemeral "tui" cron jobs — those fire in the
    # TUI process, so a TUI-set reminder is never forwarded to an IM channel.
    from unittest.mock import MagicMock

    from pico.cli.gateway_commands import _build_gateway_channels

    cfg = MagicMock()
    for name in ("feishu", "qq", "wecom"):
        ch = MagicMock()
        ch.enabled = False
        setattr(cfg.channels, name, ch)
    assert _build_gateway_channels(cfg) == set()  # no IM enabled, and no "tui"


def test_gateway_channels_excludes_tui_alongside_enabled_im() -> None:
    from unittest.mock import MagicMock

    from pico.cli.gateway_commands import _build_gateway_channels

    cfg = MagicMock()
    for name in ("feishu", "qq", "wecom"):
        ch = MagicMock()
        ch.enabled = name == "feishu"
        setattr(cfg.channels, name, ch)
    result = _build_gateway_channels(cfg)
    assert "tui" not in result
    assert "feishu" in result
    assert "qq" not in result


def test_stop_dispatch_cancels_both_scheduler_and_subagents() -> None:
    """The gateway ``/stop`` path must fan out to BOTH the scheduler lane cancel
    and the subagent-session cancel, summing their counts.

    ``_inbound_dispatch`` is a closure nested inside the gateway serve command
    with no import seam, so this pins the /stop branch of the command source:
    dropping either cancel call (or the summed count) breaks this test.
    """
    import inspect

    from pico.cli import gateway_commands

    src = inspect.getsource(gateway_commands.register)
    stop_branch = src.split('if cmd == "/stop":', 1)[1].split('elif cmd == "/restart":', 1)[0]
    assert "cancel_conversation(cid)" in stop_branch
    assert "cancel_by_session(cid)" in stop_branch
    assert "stopped +=" in stop_branch


# ---------------------------------------------------------------------------
# build_model_routing — routing backend selection
# ---------------------------------------------------------------------------

from types import SimpleNamespace

from pico.cli.gateway_commands import build_model_routing
from pico.config.schema import ModelEndpoint, RoutingConfig
from pico.providers.per_model_provider import PerModelProvider
from pico.routing.knn_router import KNNModelRouter
from pico.routing.router import ModelRouter


class _FakeProvider:
    def get_default_model(self):
        return "default-model"


def _routing_config_obj(routing):
    return SimpleNamespace(
        routing=routing,
        providers=SimpleNamespace(openrouter=SimpleNamespace(api_key="")),
        agents=SimpleNamespace(defaults=SimpleNamespace(model="default-model")),
    )


def test_build_routing_disabled_returns_same_provider():
    prov = _FakeProvider()
    router, out = build_model_routing(_routing_config_obj(RoutingConfig(enabled=False)), prov)
    assert router is None
    assert out is prov


def test_build_routing_knn_wraps_provider():
    routing = RoutingConfig(
        enabled=True,
        backend="knn",
        embedding_endpoint="http://e/embed",
        models=[
            ModelEndpoint(model="small", api_base="http://a/v1"),
            ModelEndpoint(model="large", api_base="http://b/v1"),
        ],
    )
    router, out = build_model_routing(_routing_config_obj(routing), _FakeProvider())
    assert isinstance(router, KNNModelRouter)
    assert isinstance(out, PerModelProvider)


def test_build_routing_ecoclaw_with_key_keeps_provider():
    routing = RoutingConfig(enabled=True, backend="ecoclaw", api_key="sk-or-x")
    prov = _FakeProvider()
    router, out = build_model_routing(_routing_config_obj(routing), prov)
    assert isinstance(router, ModelRouter)
    assert out is prov


def test_build_routing_ecoclaw_no_key_disabled():
    routing = RoutingConfig(enabled=True, backend="ecoclaw", api_key="")
    prov = _FakeProvider()
    router, out = build_model_routing(_routing_config_obj(routing), prov)
    assert router is None
    assert out is prov
