from __future__ import annotations

import asyncio
import importlib.metadata
import json
import re
import sys
from pathlib import Path
from typing import Any

from pico.agent.spine_runner import AgentTurnRunner
from pico.config.paths import RuntimePaths
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

_DISABLED_TOOLS = [
    "ask_user",
    "edit_file",
    "exec",
    "find",
    "grep",
    "list_dir",
    "message",
    "spawn",
    "understand_media",
    "web_fetch",
    "web_search",
]


class DeterministicTaskProvider(LLMProvider):
    def __init__(self, spec: dict[str, Any]) -> None:
        super().__init__()
        self._spec = spec
        self.calls: list[dict[str, Any]] = []
        self.used_memory = False
        self._read_requested = False
        self._write_requested = False

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
        self.calls.append(
            {
                "message_count": len(messages),
                "model": model,
                "tool_count": len(tools or ()),
            }
        )
        if self._spec["stage"] == "prime":
            return LLMResponse(content="Prior repository work recorded.", usage=_usage())
        if self._write_requested:
            return LLMResponse(content="Result artifact written.", usage=_usage())

        task_id = self._spec["task_id"]
        task_class = self._spec["task_class"]
        transcript = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        value = None
        if task_class in {"fact", "experience"}:
            value = _extract_marker(transcript, "PICO_MEMORY_FACT", task_id)
            self.used_memory = value is not None
        if value is None:
            value = _extract_marker(transcript, "PICO_REPO_FACT", task_id)
        if value is not None:
            self._write_requested = True
            content = json.dumps(
                {"task_id": task_id, "value": value},
                ensure_ascii=False,
                sort_keys=True,
            )
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"write-{task_id}",
                        name="write_file",
                        arguments={
                            "path": self._spec["output_path"],
                            "content": content + "\n",
                        },
                    )
                ],
                usage=_usage(),
            )
        if self._read_requested:
            return LLMResponse(content="Repository evidence was not parseable.", usage=_usage())
        self._read_requested = True
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id=f"read-{task_id}",
                    name="read_file",
                    arguments={"path": self._spec["source_path"]},
                )
            ],
            usage=_usage(),
        )

    def get_default_model(self) -> str:
        return "picobench/deterministic-task-policy-v1"


class RecallRecorder:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.calls = 0
        self.hits: list[dict[str, Any]] = []

    async def recall(self, *args, **kwargs):
        self.calls += 1
        hits = await self._delegate.recall(*args, **kwargs)
        self.hits = [
            {
                "metadata": hit.metadata,
                "score": hit.score,
                "text": hit.text,
            }
            for hit in hits
        ]
        return hits


def _context_factory(recorder_sink: list[RecallRecorder]):
    def factory(**kwargs):
        backend = kwargs.get("backend")
        if backend is not None:
            recorder = RecallRecorder(backend)
            recorder_sink.append(recorder)
            kwargs["backend"] = recorder
        return build_context_engine(**kwargs)

    return factory


async def run_turn(spec: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(spec["workspace"]).resolve()
    state = Path(spec["state_root"]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    provider = DeterministicTaskProvider(spec)
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.model = provider.get_default_model()
    config.agents.defaults.max_tokens = 512
    config.agents.defaults.context_window_tokens = 8_192
    config.agents.defaults.max_tool_iterations = 4
    config.agents.defaults.enable_personalization = False
    config.routing.enabled = False
    config.tools.restrict_to_workspace = True
    config.tools.disabled_tools = _DISABLED_TOOLS
    config.tools.mcp_servers = {}
    config.tools.tool_search.enabled = False
    pico_config = PicoConfig()
    memory_enabled = spec["arm_id"] == "memory_on"
    pico_config.memory.backend = "myna" if memory_enabled else None
    pico_config.skill_forge.enabled = False
    pico_config.skill_forge.router.enabled = False
    pico_config.runtime.checkpoint.policy = "never"
    pico_config.base = config
    pico_config.token_wise.smart_routing.enabled = False

    build_calls = 0
    if not memory_enabled:
        from pico.plugin.registry import PluginRegistry

        original = PluginRegistry.build_memory_backend

        def counted(self, *args, **kwargs):
            nonlocal build_calls
            build_calls += 1
            return original(self, *args, **kwargs)

        PluginRegistry.build_memory_backend = counted

    recorders: list[RecallRecorder] = []
    from pico.cli._runtime_assembly import assemble_runtime

    runtime = assemble_runtime(
        config,
        pico_config,
        provider=provider,
        cron_service=None,
        interactive=False,
        context_engine_factory=_context_factory(recorders),
        paths=RuntimePaths(workspace=workspace, state=state),
    )
    operations: list[str] = []
    events: list[Any] = []
    await runtime.start_memory_backend()
    if memory_enabled:
        operations.append("start")
    runner = AgentTurnRunner(runtime.agent_loop, stream=False)

    async def sink(event: Any) -> None:
        events.append(event)

    scheduler = Scheduler(runner, OriginPools(user=1, system=1), sink)
    request = TurnRequest(
        origin=Origin.USER,
        source=Source(
            channel="picobench-myna",
            chat_id=spec["session_id"],
            sender_id="picobench-user",
            chat_type=ChatType.DM,
        ),
        conversation=spec["session_id"],
        text=spec["prompt"],
        message_id=spec["message_id"],
    )
    outcome = None
    turn_error: dict[str, str] | None = None
    close_error: dict[str, str] | None = None
    try:
        try:
            outcome = await asyncio.wait_for(
                scheduler.submit(request).result(),
                timeout=float(spec.get("timeout_seconds", 120)),
            )
            if memory_enabled:
                if spec["stage"] == "evaluate":
                    operations.append("recall")
                operations.append("store")
        except Exception as exc:
            turn_error = _error(exc)
    finally:
        await scheduler.shutdown(grace=5)
        try:
            await runtime.close()
            if memory_enabled:
                operations.append("stop")
        except Exception as exc:
            close_error = _error(exc)

    terminal_event = next(
        (event for event in reversed(events) if isinstance(event, TurnEnded | TurnFailed)),
        None,
    )
    terminal = (
        "failed"
        if isinstance(terminal_event, TurnFailed)
        else "completed"
        if isinstance(terminal_event, TurnEnded)
        else "missing"
    )
    recorder = recorders[0] if recorders else None
    return {
        "backend_module": type(runtime.backend).__module__ if runtime.backend is not None else None,
        "close_error": close_error,
        "memory_backend_build_calls": build_calls,
        "memory_hits": outcome.memory_hits if outcome is not None else 0,
        "model_calls": provider.calls,
        "myna_operations": operations,
        "recall_calls": recorder.calls if recorder is not None else 0,
        "recall_hits": recorder.hits if recorder is not None else [],
        "terminal": terminal,
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
        "used_memory": provider.used_memory,
    }


def installed_identity() -> dict[str, Any]:
    pico = importlib.metadata.distribution("pico-harness")
    myna = importlib.metadata.distribution("myna-memory")
    return {
        "entry_points": sorted(
            [entry.name, entry.value] for entry in importlib.metadata.entry_points(group="pico.plugins")
        ),
        "myna": {
            "location": str(myna.locate_file("").resolve()),
            "version": myna.version,
        },
        "pico": {
            "location": str(pico.locate_file("").resolve()),
            "version": pico.version,
        },
        "python": sys.version,
    }


def _extract_marker(transcript: str, marker: str, task_id: str) -> str | None:
    match = re.search(
        rf"{re.escape(marker)}\[{re.escape(task_id)}\]=([^\\\"\n]+)",
        transcript,
    )
    return match.group(1).strip() if match else None


def _usage() -> dict[str, int]:
    return {"prompt_tokens": 32, "completion_tokens": 8, "total_tokens": 40}


def _error(exc: Exception) -> dict[str, str]:
    return {
        "code": str(getattr(exc, "code", type(exc).__name__)),
        "message": str(exc),
        "type": type(exc).__name__,
    }


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    mode = spec["worker_mode"]
    if mode == "identity":
        result = installed_identity()
    elif mode == "turn":
        result = asyncio.run(run_turn(spec))
    else:
        raise ValueError(f"unknown worker mode: {mode}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
