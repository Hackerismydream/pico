from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

_DISABLED_TOOLS = [
    "write_file",
    "edit_file",
    "list_dir",
    "grep",
    "find",
    "exec",
    "web_search",
    "web_fetch",
    "message",
    "spawn",
    "ask_user",
    "cron",
]


class _ObservedProvider:
    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self.stream_calls = 0
        self.non_stream_calls = 0
        self.failure_category: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    async def chat_with_retry(self, **kwargs: Any):
        self.non_stream_calls += 1
        response = await self._provider.chat_with_retry(**kwargs)
        if response.finish_reason == "error":
            classification = response.error_classification
            self.failure_category = classification.category if classification is not None else "unknown"
        return response

    async def chat_stream(self, **kwargs: Any):
        self.stream_calls += 1
        try:
            async for chunk in self._provider.chat_stream(**kwargs):
                yield chunk
        except Exception as exc:
            classifier = getattr(self._provider, "classify_error", None)
            classification = classifier(exc) if classifier is not None else None
            self.failure_category = classification.category if classification is not None else "unknown"
            raise


class _RpcFrames:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.terminal = asyncio.Event()

    async def send(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)
        event = frame.get("params", {}).get("event", {})
        if event.get("type") in {"message.complete", "error"}:
            self.terminal.set()

    @property
    def events(self) -> list[dict[str, Any]]:
        return [frame["params"]["event"] for frame in self.frames if frame.get("method") == "event"]


class _Channel:
    name = "probe"

    def __init__(self) -> None:
        from pico.spine.delivery import Capabilities

        self.capabilities = Capabilities()
        self.sent: list[tuple[str, str, list[str] | None]] = []
        self.intake: Any = None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, chat_id: str, content: str, media: list[str] | None = None) -> None:
        self.sent.append((chat_id, content, media))


def _source(host: str):
    from pico.spine import ChatType, Source

    return Source(
        channel="probe" if host == "gateway" else host,
        chat_id="live",
        sender_id="probe",
        chat_type=ChatType.DM,
    )


def _classify(
    *,
    turn_completed: bool,
    output_verified: bool,
    tool_names: list[str],
    host_errors: list[str],
    provider: _ObservedProvider,
    host: str,
    tool_calls: int,
    tool_failures: int,
    total_tokens: int,
) -> tuple[str, str]:
    if provider.failure_category is not None:
        category = provider.failure_category
        status = (
            "infrastructure_failure"
            if category
            in {
                "auth",
                "billing",
                "rate_limit",
                "server",
                "network",
                "model_unavailable",
            }
            else "failed"
        )
        return status, f"provider_{category}"
    if not turn_completed:
        return "failed", "turn_failed"
    if host_errors:
        return "failed", "host_reported_error"
    if tool_names != ["read_file"]:
        return "failed", "unexpected_tool_policy"
    if tool_calls < 1:
        return "inconclusive", "model_did_not_call_tool"
    if tool_failures:
        return "failed", "tool_call_failed"
    if total_tokens <= 0:
        return "failed", "empty_usage"
    if not output_verified:
        return "failed", "sentinel_not_returned"
    if host == "tui" and provider.stream_calls < 2:
        return "failed", "stream_path_not_observed"
    if host != "tui" and provider.non_stream_calls < 2:
        return "failed", "non_stream_path_not_observed"
    return "passed", ""


async def _run(host: str) -> dict[str, Any]:
    import pico
    from pico.cli._gateway_spine import build_gateway
    from pico.cli._helpers import make_provider
    from pico.cli._runtime_assembly import assemble_runtime
    from pico.config.pico import PicoConfig
    from pico.config.schema import Config
    from pico.spine import Origin, TurnRequest
    from pico.tui_rpc.dispatcher import Dispatcher
    from pico.tui_rpc.methods import turn as turn_methods
    from pico.tui_rpc.methods.turn import register_turn_methods
    from pico.tui_rpc.spine import build_tui
    from pico.tui_rpc.subscriptions import SubscriptionEmitter

    workspace = Path(os.environ["PICO_PROBE_WORKSPACE"]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    expected = os.environ["PICO_PROBE_SENTINEL"]
    (workspace / "sentinel.txt").write_text(expected, encoding="utf-8")

    provider_name = os.environ["PICO_LIVE_PROVIDER"]
    model = os.environ["PICO_LIVE_MODEL"]
    api_key = os.environ["PICO_LIVE_API_KEY"]
    api_base = os.environ.get("PICO_LIVE_BASE_URL", "")

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.provider = provider_name
    config.agents.defaults.model = model
    config.agents.defaults.temperature = 0.0
    config.agents.defaults.max_tool_iterations = 6
    config.tools.restrict_to_workspace = True
    config.tools.disabled_tools = list(_DISABLED_TOOLS)
    provider_config = getattr(config.providers, provider_name, None)
    if provider_config is None:
        raise ValueError(f"unsupported provider: {provider_name}")
    provider_config.api_key = api_key
    if api_base:
        provider_config.api_base = api_base

    provider = _ObservedProvider(make_provider(config))
    pico_config = PicoConfig(base=config)
    pico_config.plugins.disabled = []
    pico_config.memory.backend = None
    pico_config.skill_forge.enabled = False
    pico_config.skill_forge.router.enabled = False
    pico_config.skill_forge.rewrite_enabled = False
    pico_config.skill_forge.llm_gate_enabled = False
    pico_config.token_wise.enabled = False
    pico_config.runtime.checkpoint.policy = "never"
    config_document = config.model_dump(mode="json", by_alias=True)
    config_document["providers"][provider_name]["apiKey"] = ""
    config_document["providers"][provider_name]["apiBase"] = ""
    config_document.update(
        {
            "memory": pico_config.memory.model_dump(mode="json", by_alias=True),
            "plugins": pico_config.plugins.model_dump(mode="json", by_alias=True),
            "skillForge": pico_config.skill_forge.model_dump(mode="json", by_alias=True),
            "tokenWise": pico_config.token_wise.model_dump(mode="json", by_alias=True),
            "runtime": pico_config.runtime.model_dump(mode="json", by_alias=True),
        }
    )
    config_path = workspace / "probe-config.json"
    config_path.write_text(json.dumps(config_document), encoding="utf-8")
    config_path.chmod(0o600)
    config_text = config_path.read_text(encoding="utf-8")
    if any(value and value in config_text for value in (api_key, api_base)):
        raise RuntimeError("probe config contains live provider credential")
    runtime = assemble_runtime(
        config,
        pico_config,
        provider=provider,
        cron_service=None,
        interactive=host != "cli",
    )

    prompt = (
        "Call read_file with path sentinel.txt. The file contains a private "
        "verification marker. After reading it, include that exact marker in "
        "your final answer. Do not guess or answer before the tool result."
    )
    request = TurnRequest(
        origin=Origin.USER,
        source=_source(host),
        text=prompt,
        conversation=f"{host}:live",
    )
    teardown = None
    subscription_id = None
    outcome = None
    host_errors: list[str] = []
    output_text = ""
    event_types: list[str] = []
    tool_calls = 0
    tool_failures = 0
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    turn_completed = False
    registered_tool_names: list[str] = []
    try:
        if host == "cli":
            from typer.testing import CliRunner

            from pico.agent.loop import AgentLoop
            from pico.cli import agent_commands
            from pico.cli.commands import app

            captured: dict[str, Any] = {}
            original_run_turn = AgentLoop.run_turn
            original_make_provider = agent_commands.make_provider

            async def _capture_run_turn(self, *args, **kwargs):
                captured["tool_names"] = sorted(self.tools.tool_names)
                captured["outcome"] = await original_run_turn(self, *args, **kwargs)
                return captured["outcome"]

            def _invoke_cli():
                runner = CliRunner()
                return runner.invoke(
                    app,
                    [
                        "run",
                        "--message",
                        prompt,
                        "--workspace",
                        str(workspace),
                        "--config",
                        str(config_path),
                        "--no-markdown",
                    ],
                )

            AgentLoop.run_turn = _capture_run_turn
            agent_commands.make_provider = lambda _config: provider
            try:
                cli_result = await asyncio.to_thread(_invoke_cli)
            finally:
                agent_commands.make_provider = original_make_provider
                AgentLoop.run_turn = original_run_turn
            output_text = cli_result.stdout
            outcome = captured.get("outcome")
            registered_tool_names = captured.get("tool_names", [])
            if cli_result.exit_code != 0:
                host_errors.append("cli_exit_nonzero")
            if outcome is not None:
                turn_completed = True
                tool_calls = outcome.tool_calls
                tool_failures = outcome.tool_failures
                usage = {
                    "prompt_tokens": outcome.usage.prompt_tokens,
                    "completion_tokens": outcome.usage.completion_tokens,
                    "total_tokens": outcome.usage.total_tokens,
                }
        elif host == "tui":
            rpc_frames = _RpcFrames()
            emitter = SubscriptionEmitter(send_frame=rpc_frames.send)
            scheduler, _hub, turn_ids, submission_ids, teardown = build_tui(
                runtime.agent_loop,
                emitter,
                on_turn_end=turn_methods.clear_active,
            )
            dispatcher = Dispatcher()
            register_turn_methods(
                dispatcher,
                emitter=emitter,
                scheduler=scheduler,
                turn_ids=turn_ids,
                submission_ids=submission_ids,
            )
            session_key = request.conversation
            subscribed = await dispatcher.dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "turn.subscribe",
                    "params": {"session_key": session_key},
                }
            )
            if "error" in subscribed:
                raise RuntimeError("turn.subscribe failed")
            subscription_id = subscribed["result"]["subscription_id"]
            sent = await dispatcher.dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "turn.send",
                    "params": {
                        "session_key": session_key,
                        "submission_id": "submission-live",
                        "content": prompt,
                        "channel": "tui",
                        "chat_id": "live",
                        "sender_id": "probe",
                    },
                }
            )
            if "error" in sent or not sent.get("result", {}).get("accepted"):
                raise RuntimeError("turn.send failed")
            await asyncio.wait_for(rpc_frames.terminal.wait(), timeout=120)
            events = rpc_frames.events
            event_types = [event["type"] for event in events]
            output_text = "".join(
                str(event["payload"].get("text", "")) for event in events if event["type"] == "token.delta"
            )
            host_errors.extend(
                str(event["payload"].get("message", "error")) for event in events if event["type"] == "error"
            )
            completions = [event for event in events if event["type"] == "message.complete"]
            if completions:
                turn_completed = True
                payload_usage = completions[-1]["payload"].get("usage", {})
                usage = {
                    "prompt_tokens": int(payload_usage.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(payload_usage.get("completion_tokens", 0) or 0),
                    "total_tokens": int(payload_usage.get("total_tokens", 0) or 0),
                }
            tool_calls = sum(event["type"] == "tool.start" for event in events)
            tool_failures = sum(
                event["type"] == "tool.complete" and event["payload"].get("failed", False) for event in events
            )
        else:
            from types import SimpleNamespace

            from pico.channels.contract import Channel
            from pico.channels.intake import Intake

            channel = _Channel()
            channel.intake = Intake(
                "probe",
                SimpleNamespace(allow_from=["*"]),
            )
            if not isinstance(channel, Channel):
                raise TypeError("probe channel does not satisfy Channel")
            scheduler, hub, _readback, _sources, teardown = build_gateway(
                runtime.agent_loop,
                {"probe": channel},
            )
            handles = []

            async def _submit(req) -> None:
                handles.append(scheduler.submit(req))

            channel.intake.set_submit(_submit)
            await channel.intake.publish(
                sender_id="probe",
                chat_id="live",
                content=prompt,
                session_key=request.conversation,
            )
            if len(handles) != 1:
                raise RuntimeError("gateway intake did not submit one turn")
            outcome = await handles[0].result()
            await hub.wait_idle("probe")
            output_text = "\n".join(content for _chat, content, _media in channel.sent)
            if outcome is None:
                host_errors.append("turn_failed")
            else:
                turn_completed = True
                tool_calls = outcome.tool_calls
                tool_failures = outcome.tool_failures
                usage = {
                    "prompt_tokens": outcome.usage.prompt_tokens,
                    "completion_tokens": outcome.usage.completion_tokens,
                    "total_tokens": outcome.usage.total_tokens,
                }
    finally:
        if subscription_id is not None:
            await emitter.unregister(subscription_id)
        if host == "tui":
            turn_methods.clear_active(request.conversation)
        if teardown is not None:
            await teardown()
        await runtime.close()

    tool_names = registered_tool_names or sorted(runtime.agent_loop.tools.tool_names)
    output_verified = expected in output_text
    status, reason = _classify(
        turn_completed=turn_completed,
        output_verified=output_verified,
        tool_names=tool_names,
        host_errors=host_errors,
        provider=provider,
        host=host,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        total_tokens=usage["total_tokens"],
    )
    return {
        "status": status,
        "reason": reason,
        "host": host,
        "provider": provider_name,
        "model": model,
        "provider_failure_category": provider.failure_category,
        "stream_mode": host == "tui",
        "stream_calls": provider.stream_calls,
        "non_stream_calls": provider.non_stream_calls,
        "usage": usage,
        "tool_calls": tool_calls,
        "tool_failures": tool_failures,
        "tool_names": tool_names,
        "output_verified": output_verified,
        "event_types": event_types,
        "installed_module": str(Path(pico.__file__).resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("cli", "tui", "gateway"), required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args.host))
    except BaseException as exc:
        result = {
            "status": "failed",
            "reason": "probe_exception",
            "host": args.host,
            "error_type": type(exc).__name__,
        }
        if os.environ.get("PICO_PROBE_MODE", "live") != "live":
            result["error_detail"] = str(exc)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
