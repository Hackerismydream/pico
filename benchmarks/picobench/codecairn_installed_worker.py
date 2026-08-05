from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from pico.agent.spine_runner import AgentTurnRunner
from pico.agent.tools.base import Tool
from pico.config.pico import PicoConfig
from pico.config.schema import Config
from pico.context_engine import build_context_engine
from pico.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from pico.spine import (
    ChatType,
    Origin,
    OriginPools,
    Scheduler,
    Source,
    ToolEvent,
    TurnEnded,
    TurnFailed,
    TurnRequest,
)
from pico.spine.delivery import Capabilities, DeliveryHub, make_hub_sink

_DISABLED_TOOLS = [
    "ask_user",
    "edit_file",
    "exec",
    "find",
    "grep",
    "list_dir",
    "message",
    "read_file",
    "spawn",
    "understand_media",
    "web_fetch",
    "web_search",
    "write_file",
]
_TASK_EFFECT_ENABLED_TOOLS = {
    "exec",
    "read_file",
    "write_file",
}


class _Provider(LLMProvider):
    def __init__(self, spec: dict[str, Any]) -> None:
        super().__init__()
        self.spec = spec
        self.calls: list[dict[str, object]] = []

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    ) -> LLMResponse:
        del max_tokens, temperature, reasoning_effort, tool_choice
        serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        marker_seen = self.spec["expected_value"] in serialized
        self.calls.append(
            {
                "marker_seen": marker_seen,
                "message_count": len(messages),
                "model": model,
                "tool_count": len(tools or ()),
            }
        )
        if self.spec["mode"] == "learn":
            return LLMResponse(
                content=f"Recorded {self.spec['expected_key']}.",
                usage=_usage(),
            )
        tool_result_seen = any(message.get("role") == "tool" for message in messages)
        if marker_seen and not tool_result_seen:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="codecairn-joint-write",
                        name="joint_write_result",
                        arguments={
                            "key": self.spec["expected_key"],
                            "value": self.spec["expected_value"],
                        },
                    )
                ],
                usage=_usage(),
            )
        return LLMResponse(
            content=("Result persisted." if tool_result_seen else "The required prior context was not available."),
            usage=_usage(),
        )

    def get_default_model(self) -> str:
        return "picobench/codecairn-deterministic"


class _RecordingProvider(LLMProvider):
    _CHAT_RETRY_DELAYS = (0,)

    def __init__(
        self,
        delegate: LLMProvider,
        *,
        preserve_reasoning_content: bool = True,
    ) -> None:
        super().__init__(
            api_key=getattr(delegate, "api_key", None),
            api_base=getattr(delegate, "api_base", None),
        )
        self.delegate = delegate
        self.generation = delegate.generation
        self.preserve_reasoning_content = preserve_reasoning_content
        self.calls: list[dict[str, object]] = []

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    ) -> LLMResponse:
        response = await self.delegate.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )
        self.calls.append(
            {
                "finish_reason": response.finish_reason,
                "model": response.model,
                "usage": dict(response.usage),
            }
        )
        if not self.preserve_reasoning_content:
            response = replace(
                response,
                reasoning_content=None,
                thinking_blocks=None,
            )
        return response

    def get_default_model(self) -> str:
        return self.delegate.get_default_model()

    def classify_error(
        self,
        exc: BaseException | None = None,
        content: str | None = None,
    ):
        return self.delegate.classify_error(exc, content)


class _WriteResultTool(Tool):
    def __init__(self, workspace: Path, output_file: str) -> None:
        self.workspace = workspace
        self.output_file = output_file

    @property
    def name(self) -> str:
        return "joint_write_result"

    @property
    def description(self) -> str:
        return "Write the verified key and value to the task result artifact."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        }

    async def execute(self, **kwargs) -> str:
        output = (self.workspace / self.output_file).resolve()
        output.relative_to(self.workspace)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    str(kwargs["key"]): str(kwargs["value"]),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return "result written"


class _Outlet:
    name = "codecairn-joint"
    capabilities = Capabilities()

    def __init__(self) -> None:
        self.events: list[str] = []

    async def deliver(self, out) -> None:
        self.events.append(type(out).__name__)


class _RecallRecorder:
    def __init__(self, delegate: Any, target: Path) -> None:
        self.delegate = delegate
        self.target = target

    async def recall(self, *args, **kwargs):
        started = time.perf_counter_ns()
        hits = await self.delegate.recall(*args, **kwargs)
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        self.target.write_text(
            json.dumps(
                {
                    "hits": [
                        {
                            "metadata": hit.metadata,
                            "score": hit.score,
                            "text_contains_expected": False,
                        }
                        for hit in hits
                    ],
                    "latency_ms": latency_ms,
                    "query": args[0] if args else "",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return hits


def _context_factory(observation: Path):
    def factory(**kwargs):
        backend = kwargs.get("backend")
        if backend is not None:
            kwargs["backend"] = _RecallRecorder(backend, observation)
        return build_context_engine(**kwargs)

    return factory


async def _run_turn(spec: dict[str, Any]) -> dict[str, object]:
    workspace = Path(spec["workspace"]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    provider, config, pico_config, budget_scope = _runtime_dependencies(
        spec,
        workspace,
    )
    memory_enabled = bool(spec["memory_enabled"])
    pico_config.memory.backend = "codecairn" if memory_enabled else None
    memory_backend_build_calls = 0
    if not memory_enabled:
        from pico.plugin.registry import PluginRegistry

        original_build_memory_backend = PluginRegistry.build_memory_backend

        def counted_build_memory_backend(self, *args, **kwargs):
            nonlocal memory_backend_build_calls
            memory_backend_build_calls += 1
            return original_build_memory_backend(
                self,
                *args,
                **kwargs,
            )

        PluginRegistry.build_memory_backend = counted_build_memory_backend
    skill_forge_enabled = bool(spec.get("skill_forge_enabled", False))
    pico_config.skill_forge.enabled = skill_forge_enabled
    pico_config.skill_forge.router.enabled = skill_forge_enabled
    pico_config.skill_forge.rewrite_enabled = False
    pico_config.skill_forge.llm_gate_enabled = False
    pico_config.runtime.checkpoint.policy = "never"
    observation = Path(spec["recall_observation"]).resolve()
    if observation.exists():
        observation.unlink()

    from pico.cli._runtime_assembly import assemble_runtime

    runtime = assemble_runtime(
        config,
        pico_config,
        provider=provider,
        cron_service=None,
        interactive=False,
        context_engine_factory=_context_factory(observation),
    )
    _register_result_tool(
        runtime,
        workspace=workspace,
        output_file=spec["output_file"],
        mode=spec["mode"],
    )
    backend_module = type(runtime.backend).__module__ if runtime.backend is not None else None
    await runtime.start_memory_backend()
    runner = AgentTurnRunner(runtime.agent_loop, stream=False)
    outlet = _Outlet()
    hub = DeliveryHub(send_max_retries=0)
    hub.register(outlet)
    events: list[object] = []
    hub_sink = make_hub_sink(hub)

    async def sink(event) -> None:
        events.append(event)
        if not isinstance(event, (TurnEnded, TurnFailed)):
            await hub_sink(event)

    scheduler = Scheduler(runner, OriginPools(user=1, system=1), sink)
    request = TurnRequest(
        origin=Origin.USER,
        source=Source(
            channel=outlet.name,
            chat_id=spec["conversation_id"],
            sender_id="joint-user",
            chat_type=ChatType.DM,
        ),
        conversation=spec["conversation_id"],
        text=spec["prompt"],
        message_id=spec["message_id"],
    )
    started = time.perf_counter_ns()
    close_error: dict[str, str] | None = None
    outcome = None
    turn_error: dict[str, str] | None = None
    try:
        try:
            with budget_scope:
                outcome = await asyncio.wait_for(
                    scheduler.submit(request).result(),
                    timeout=float(spec.get("timeout_seconds", 30)),
                )
            await hub.wait_idle(outlet.name)
            if spec.get("inject_before_close") == "malformed_stage":
                journal = Path(spec["source_journal"]).resolve()
                stage = journal.with_name(f".{journal.stem}.stage.jsonl")
                stage.write_bytes(b'{"record_type":"batch"')
        except Exception as error:
            turn_error = _error(error)
    finally:
        await scheduler.shutdown(grace=5)
        await hub.aclose()
        try:
            await runtime.close()
        except Exception as error:
            close_error = _error(error)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    failure = next(
        (event for event in reversed(events) if isinstance(event, TurnFailed)),
        None,
    )
    terminal = next(
        ("cancelled" if event.cancelled else "failed" for event in reversed(events) if isinstance(event, TurnFailed)),
        "completed",
    )
    return {
        "backend_module": backend_module,
        "close_error": close_error,
        "codecairn_backend_module_loaded": ("codecairn.integrations.pico.backend" in sys.modules),
        "delivery_events": outlet.events,
        "elapsed_ms": elapsed_ms,
        "event_types": [type(event).__name__ for event in events],
        "memory_backend_build_calls": memory_backend_build_calls,
        "model_calls": provider.calls,
        "pid": os.getpid(),
        "outcome": {
            "context_path": (outcome.context_path if outcome is not None else None),
            "failure_category": (turn_error.get("category") if turn_error is not None else None),
            "injected_skill_ids": (list(outcome.injected_skill_ids) if outcome is not None else []),
            "memory_hits": (outcome.memory_hits if outcome is not None else 0),
            "status": terminal,
            "tool_calls": (outcome.tool_calls if outcome is not None else 0),
            "tool_failures": (outcome.tool_failures if outcome is not None else 0),
        },
        "terminal": terminal,
        "terminal_error": (failure.error if failure is not None else None),
        "tool_events": [
            {
                "arguments": event.arguments,
                "failed": event.failed,
                "name": event.name,
                "phase": event.phase.value,
                "tool_call_id": event.tool_call_id,
            }
            for event in events
            if isinstance(event, ToolEvent)
        ],
        "turn_error": turn_error,
    }


def _register_result_tool(
    runtime: Any,
    *,
    workspace: Path,
    output_file: str,
    mode: str,
) -> bool:
    if mode != "evaluate":
        return False
    runtime.agent_loop.tools.register(
        _WriteResultTool(workspace, output_file),
    )
    return True


def _runtime_dependencies(
    spec: dict[str, Any],
    workspace: Path,
) -> tuple[
    LLMProvider,
    Config,
    PicoConfig,
    contextlib.AbstractContextManager[None],
]:
    provider_spec = spec.get("provider")
    if not isinstance(provider_spec, dict) or provider_spec.get("mode") != "real":
        provider = _Provider(spec)
        config = Config()
        pico_config = PicoConfig()
        budget_scope = contextlib.nullcontext()
    else:
        from pico.cli._helpers import make_provider

        private = json.loads(
            Path(str(provider_spec["private_config_path"])).read_text(
                encoding="utf-8",
            )
        )
        config = Config.model_validate(private["config"])
        pico_config = PicoConfig.model_validate(private["pico_config"])
        delegate = make_provider(config)
        configure_transport_retries = getattr(
            delegate,
            "set_transport_num_retries",
            None,
        )
        if not callable(configure_transport_retries):
            raise RuntimeError(
                "installed provider does not expose transport retry control",
            )
        configure_transport_retries(0)
        provider = _RecordingProvider(
            delegate,
            preserve_reasoning_content=(spec.get("mode") != "task_effect"),
        )
        budget_scope = contextlib.nullcontext()

    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.model = provider.get_default_model()
    config.agents.defaults.max_tokens = int(spec.get("max_tokens", 512))
    config.agents.defaults.context_window_tokens = int(
        spec.get(
            "context_window_tokens",
            config.agents.defaults.context_window_tokens,
        )
    )
    task_effect = spec.get("mode") == "task_effect"
    if task_effect and not bool(
        spec.get(
            "skill_forge_enabled",
            False,
        )
    ):
        pico_config.skill_forge.router.top_k = 0
    config.agents.defaults.max_tool_iterations = int(
        spec.get(
            "max_tool_iterations",
            8 if task_effect else 4,
        )
    )
    config.agents.defaults.enable_personalization = False
    config.routing.enabled = False
    config.tools.restrict_to_workspace = True
    config.tools.disabled_tools = [
        tool for tool in _DISABLED_TOOLS if not task_effect or tool not in _TASK_EFFECT_ENABLED_TOOLS
    ]
    config.tools.mcp_servers = {}
    config.tools.tool_search.enabled = False
    pico_config.base = config
    pico_config.token_wise.smart_routing.enabled = False
    return provider, config, pico_config, budget_scope


async def _backend_failure(spec: dict[str, Any]) -> dict[str, object]:
    workspace = Path(spec["workspace"]).resolve()
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.model = "picobench/codecairn-deterministic"
    pico_config = PicoConfig()
    pico_config.memory.backend = "codecairn"
    pico_config.skill_forge.enabled = False
    pico_config.runtime.checkpoint.policy = "never"

    from pico.cli._runtime_assembly import assemble_runtime

    runtime = assemble_runtime(
        config,
        pico_config,
        provider=_Provider(
            {
                "mode": "learn",
                "expected_key": "failure",
                "expected_value": "failure",
            }
        ),
        cron_service=None,
        interactive=False,
    )
    try:
        await runtime.start_memory_backend()
    except Exception as error:
        return {"phase": "start", "error": _error(error)}
    try:
        await runtime.close()
    except Exception as error:
        return {"phase": "stop", "error": _error(error)}
    return {"phase": "none", "error": None}


def _installed_identity() -> dict[str, object]:
    pico = importlib.metadata.distribution("pico-harness")
    codecairn = importlib.metadata.distribution("codecairn")
    entry_points = sorted(
        {
            (entry_point.group, entry_point.name, entry_point.value)
            for entry_point in importlib.metadata.entry_points(group="pico.plugins")
        }
    )
    return {
        "codecairn": {
            "direct_url": _direct_url(codecairn),
            "location": str(codecairn.locate_file("").resolve()),
            "version": codecairn.version,
        },
        "entry_points": [list(item) for item in entry_points],
        "pico": {
            "direct_url": _direct_url(pico),
            "location": str(pico.locate_file("").resolve()),
            "version": pico.version,
        },
        "python": sys.version,
        "sys_path": sys.path,
    }


def _direct_url(distribution: importlib.metadata.Distribution) -> object:
    value = distribution.read_text("direct_url.json")
    return json.loads(value) if value else None


def _usage() -> dict[str, int]:
    return {
        "completion_tokens": 8,
        "prompt_tokens": 32,
        "total_tokens": 40,
    }


def _error(error: Exception) -> dict[str, str]:
    message = str(error)
    code = getattr(error, "code", type(error).__name__)
    remediation = message.split(": ", 1)[1] if ": " in message else message
    value = {
        "code": str(code),
        "message": message,
        "remediation": remediation,
        "type": type(error).__name__,
    }
    category = getattr(error, "category", None)
    if category is not None:
        value["category"] = str(category)
    return value


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    mode = spec["worker_mode"]
    if mode == "identity":
        result = _installed_identity()
    elif mode == "turn":
        result = asyncio.run(_run_turn(spec))
    elif mode == "backend_failure":
        result = asyncio.run(_backend_failure(spec))
    else:
        raise ValueError(f"unknown worker mode: {mode}")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
