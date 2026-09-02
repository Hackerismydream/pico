from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from pico.agent.spine_runner import AgentTurnRunner
from pico.config.paths import RuntimePaths
from pico.config.pico import PicoConfig
from pico.config.schema import Config
from pico.context_engine import build_context_engine
from pico.memory_engine.backend import Memory
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


class MemoryOperationRecorder:
    def __init__(self, delegate: Any, *, stage: str, agent_track_only: bool = False) -> None:
        self._delegate = delegate
        self._stage = stage
        self._agent_track_only = agent_track_only
        self.calls = 0
        self.hits: list[dict[str, Any]] = []
        self.receipt: list[dict[str, Any]] = []

    async def start(self) -> None:
        await self._record("start", self._delegate.start())

    async def recall(self, *args, **kwargs):
        self.calls += 1
        if self._agent_track_only and kwargs.get("user_id") is not None:
            self.hits = []
            self.receipt.append(
                {
                    "schema": "pico.picobench.myna-agent-task-effect.memory-operation.v2",
                    "operation": "recall",
                    "outcome": "succeeded",
                    "phase": self._stage,
                }
            )
            return []
        hits = await self._record("recall", self._delegate.recall(*args, **kwargs))
        self.hits = [
            {
                "metadata": hit.metadata,
                "score": hit.score,
                "text": hit.text,
            }
            for hit in hits
        ]
        return hits

    async def store(self, *args, **kwargs) -> None:
        if self._agent_track_only:
            self._record_suppressed("store")
            return
        await self._record("store", self._delegate.store(*args, **kwargs))

    async def feedback(self, *args, **kwargs) -> None:
        if self._agent_track_only:
            self._record_suppressed("feedback")
            return
        await self._record("feedback", self._delegate.feedback(*args, **kwargs))

    async def stop(self) -> None:
        await self._record("stop", self._delegate.stop())

    async def _record(self, operation: str, awaitable):
        try:
            result = await awaitable
        except Exception as exc:
            self.receipt.append(
                {
                    "schema": "pico.picobench.myna-agent-task-effect.memory-operation.v2",
                    "operation": operation,
                    "outcome": "failed",
                    "phase": self._stage,
                    "error": _error(exc),
                }
            )
            raise
        self.receipt.append(
            {
                "schema": "pico.picobench.myna-agent-task-effect.memory-operation.v2",
                "operation": operation,
                "outcome": "succeeded",
                "phase": self._stage,
            }
        )
        return result

    def _record_suppressed(self, operation: str) -> None:
        self.receipt.append(
            {
                "schema": "pico.picobench.myna-agent-task-effect.memory-operation.v2",
                "operation": operation,
                "outcome": "succeeded",
                "phase": self._stage,
            }
        )


class _SpecSkillBackend:
    def __init__(self, skill: dict[str, Any]) -> None:
        self._skill = skill

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def store(self, session_id, messages) -> None:
        return None

    async def feedback(self, signals) -> None:
        return None

    async def recall(self, query, *, user_id=None, agent_id=None, top_k=5):
        if agent_id is None or top_k < 1:
            return []
        skill = self._skill
        return [
            Memory(
                text=(f"---\nname: {skill['name']}\ndescription: {skill['description']}\n---\n\n{skill['content']}"),
                score=1.0,
                metadata={
                    "backend": "picobench-oracle",
                    "name": skill["name"],
                    "description": skill["description"],
                    "qualified_id": skill["qualified_id"],
                    "revision_id": skill["revision_id"],
                    "source_experience_ids": skill.get("source_experience_ids", []),
                },
            )
        ]


def _context_factory(recorder_sink: list[MemoryOperationRecorder], *, stage: str, agent_track_only: bool):
    def factory(**kwargs):
        backend = kwargs.get("backend")
        if backend is not None:
            recorder = MemoryOperationRecorder(backend, stage=stage, agent_track_only=agent_track_only)
            recorder_sink.append(recorder)
            kwargs["backend"] = recorder
        return build_context_engine(**kwargs)

    return factory


class ProviderRecorder(LLMProvider):
    def __init__(self, delegate: LLMProvider, *, oracle_gate_skill_id: str | None = None) -> None:
        super().__init__(api_key=delegate.api_key, api_base=delegate.api_base)
        self._delegate = delegate
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.generation = delegate.generation
        self.failures: list[dict[str, Any]] = []
        self._oracle_gate_skill_id = oracle_gate_skill_id

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        messages = kwargs.get("messages") if "messages" in kwargs else args[0] if args else []
        prompt = str(messages[0].get("content", "")) if messages else ""
        if self._oracle_gate_skill_id and "skill selector for an autonomous agent" in prompt:
            return LLMResponse(
                content=json.dumps({"plan": "oracle ability routing", "skills": [self._oracle_gate_skill_id]}),
                usage={},
            )
        try:
            response = await self._delegate.chat(*args, **kwargs)
        except Exception as exc:
            self.failures.append(_provider_failure_receipt(exc))
            raise
        self.input_tokens += int(response.usage.get("prompt_tokens", response.usage.get("input_tokens", 0)) or 0)
        self.output_tokens += int(response.usage.get("completion_tokens", response.usage.get("output_tokens", 0)) or 0)
        if response.finish_reason == "error":
            category = (
                response.error_classification.category if response.error_classification is not None else "unknown"
            )
            self.failures.append(
                {
                    "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
                    "failure_class": _provider_category_class(category),
                    "phase": "provider_response",
                    "error": {
                        "code": category,
                        "message": response.content or "Provider returned an error response",
                        "type": "ProviderErrorResponse",
                    },
                }
            )
        return response

    def get_default_model(self) -> str:
        return self._delegate.get_default_model()


async def run_turn(
    spec: dict[str, Any],
    *,
    provider_override: LLMProvider | None = None,
    backend_override: Any | None = None,
) -> dict[str, Any]:
    workspace = Path(spec["workspace"]).resolve()
    state = Path(spec["state_root"]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    provider_mode = spec.get("provider_mode", "deterministic")
    delegate = provider_override or (
        _build_live_provider(spec) if provider_mode == "live" else DeterministicTaskProvider(spec)
    )
    budget_attempts_before = _provider_request_attempts(delegate)
    oracle_skill = spec.get("oracle_skill")
    oracle_gate_skill_id = (
        str(oracle_skill.get("qualified_id")) if spec.get("oracle_gate") and isinstance(oracle_skill, dict) else None
    )
    provider = ProviderRecorder(delegate, oracle_gate_skill_id=oracle_gate_skill_id)
    if backend_override is None and isinstance(oracle_skill, dict):
        backend_override = _SpecSkillBackend(oracle_skill)
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.model = provider.get_default_model()
    config.agents.defaults.max_tokens = int(spec.get("max_output_tokens_per_call", 512))
    config.agents.defaults.context_window_tokens = int(spec.get("context_window_tokens", 8_192))
    config.agents.defaults.max_tool_iterations = int(spec.get("max_tool_iterations", 4))
    config.agents.defaults.enable_personalization = False
    config.routing.enabled = False
    config.tools.restrict_to_workspace = True
    config.tools.disabled_tools = list(spec.get("disabled_tools", _DISABLED_TOOLS))
    config.tools.mcp_servers = {}
    config.tools.tool_search.enabled = False
    pico_config = PicoConfig()
    memory_enabled = bool(spec.get("memory_enabled", spec["arm_id"] == "memory_on"))
    pico_config.memory.backend = "myna" if memory_enabled and backend_override is None else None
    skill_forge_enabled = bool(spec.get("skill_forge_enabled", False))
    pico_config.skill_forge.enabled = skill_forge_enabled
    pico_config.skill_forge.router.enabled = skill_forge_enabled
    pico_config.skill_forge.rewrite_enabled = False
    pico_config.skill_forge.llm_gate_enabled = bool(spec.get("llm_gate_enabled", False))
    pico_config.skill_forge.llm_gate_max_tokens = int(
        spec.get("llm_gate_max_tokens", pico_config.skill_forge.llm_gate_max_tokens)
    )
    pico_config.runtime.checkpoint.policy = "never"
    pico_config.base = config
    pico_config.token_wise.smart_routing.enabled = False

    build_calls = 0
    original_memory_builder = None
    if not memory_enabled:
        from pico.plugin.registry import PluginRegistry

        original = PluginRegistry.build_memory_backend
        original_memory_builder = original

        def counted(self, *args, **kwargs):
            nonlocal build_calls
            build_calls += 1
            return original(self, *args, **kwargs)

        PluginRegistry.build_memory_backend = counted

    recorders: list[MemoryOperationRecorder] = []
    from pico.cli._runtime_assembly import assemble_runtime

    def build_runtime():
        return assemble_runtime(
            config,
            pico_config,
            provider=provider,
            cron_service=None,
            interactive=False,
            context_engine_factory=_context_factory(
                recorders,
                stage=spec["stage"],
                agent_track_only=bool(spec.get("agent_track_only", False)),
            ),
            paths=RuntimePaths(workspace=workspace, state=state),
        )

    try:
        runtime = build_runtime()
    except Exception as exc:
        failure_class = "memory_backend" if memory_enabled else "infrastructure"
        failure_receipt = {
            "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
            "failure_class": failure_class,
            "phase": "runtime_assembly",
            "error": _error(exc),
        }
        return {
            "backend_module": None,
            "close_error": None,
            "memory_backend_build_calls": build_calls,
            "memory_hits": 0,
            "model_calls": getattr(delegate, "calls", []),
            "input_tokens": provider.input_tokens,
            "output_tokens": provider.output_tokens,
            "provider_calls": _provider_request_attempts(
                delegate,
                baseline=budget_attempts_before,
                fallback=provider.calls,
            ),
            "failure_class": failure_class,
            "failure_receipt": failure_receipt,
            "failure_receipts": [failure_receipt],
            "memory_operation_receipt": [],
            "myna_operations": [],
            "recall_calls": 0,
            "recall_hits": [],
            "terminal": "failed",
            "tool_events": [],
            "turn_error": _error(exc),
            "used_memory": bool(getattr(delegate, "used_memory", False)),
        }
    finally:
        if original_memory_builder is not None:
            PluginRegistry.build_memory_backend = original_memory_builder
    if backend_override is not None:
        recorder = MemoryOperationRecorder(
            backend_override,
            stage=spec["stage"],
            agent_track_only=bool(spec.get("agent_track_only", False)),
        )
        recorders.append(recorder)
        runtime.agent_loop.context_engine = build_context_engine(
            workspace=workspace,
            config=pico_config.context,
            builder=runtime.agent_loop.context,
            provider=runtime.agent_loop.provider,
            model=runtime.agent_loop.model,
            context_window_tokens=runtime.agent_loop.context_window_tokens,
            get_tool_definitions=runtime.agent_loop.tools.get_definitions,
            backend=recorder,
            memory_config=pico_config.memory,
            skill_forge_router_config=pico_config.skill_forge.router,
            skill_forge_config=pico_config.skill_forge,
        )
    else:
        recorder = recorders[0] if recorders else None
    backend_module = (
        type(backend_override).__module__
        if backend_override is not None
        else type(runtime.backend).__module__
        if runtime.backend is not None
        else None
    )
    if recorder is not None:
        runtime.backend = recorder
        runtime.agent_loop.backend = recorder
    events: list[Any] = []

    async def sink(event: Any) -> None:
        events.append(event)

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
    scheduler: Scheduler | None = None
    try:
        try:
            await runtime.start_memory_backend()
            runner = AgentTurnRunner(runtime.agent_loop, stream=False)
            scheduler = Scheduler(runner, OriginPools(user=1, system=1), sink)
            with _provider_scope(spec):
                outcome = await asyncio.wait_for(
                    scheduler.submit(request).result(),
                    timeout=float(spec.get("timeout_seconds", 120)),
                )
        except Exception as exc:
            turn_error = _error(exc)
    finally:
        if scheduler is not None:
            await scheduler.shutdown(grace=5)
        try:
            await runtime.close()
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
    memory_failure = (
        next(
            (row for row in reversed(recorder.receipt) if row["outcome"] == "failed"),
            None,
        )
        if recorder is not None
        else None
    )
    memory_failure_receipt = None
    if memory_failure is not None:
        memory_failure_receipt = {
            "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
            "failure_class": "memory_backend",
            "phase": memory_failure["phase"],
            "operation": memory_failure["operation"],
            "error": memory_failure["error"],
        }
    infrastructure_failure_receipt = None
    if (
        not provider.failures
        and memory_failure_receipt is None
        and (turn_error is not None or close_error is not None or terminal == "failed")
    ):
        infrastructure_failure_receipt = {
            "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
            "failure_class": "infrastructure",
            "phase": "turn_execution",
            "error": turn_error
            or close_error
            or {
                "code": "turn_failed",
                "message": terminal_event.error if isinstance(terminal_event, TurnFailed) else "Turn failed",
                "type": "TurnFailed",
            },
        }
    failure_receipts = [*provider.failures]
    if infrastructure_failure_receipt is not None:
        failure_receipts.append(infrastructure_failure_receipt)
    if memory_failure_receipt is not None:
        failure_receipts.append(memory_failure_receipt)
    failure_receipt = failure_receipts[0] if failure_receipts else None
    return {
        "backend_module": backend_module,
        "close_error": close_error,
        "memory_backend_build_calls": build_calls,
        "memory_hits": outcome.memory_hits if outcome is not None else 0,
        "model_calls": getattr(delegate, "calls", []),
        "input_tokens": provider.input_tokens,
        "injected_skill_ids": list(outcome.injected_skill_ids) if outcome is not None else [],
        "skill_candidate_ids": list(outcome.skill_candidate_ids) if outcome is not None else [],
        "skill_gate_required_ids": list(outcome.skill_gate_required_ids) if outcome is not None else [],
        "skill_gate_selected_ids": list(outcome.skill_gate_selected_ids) if outcome is not None else [],
        "skill_gate_status": outcome.skill_gate_status if outcome is not None else None,
        "skill_gate_fallback_reason": outcome.skill_gate_fallback_reason if outcome is not None else None,
        "output_tokens": provider.output_tokens,
        "provider_calls": _provider_request_attempts(
            delegate, baseline=budget_attempts_before, fallback=provider.calls
        ),
        "failure_class": failure_receipt["failure_class"] if failure_receipt is not None else None,
        "failure_receipt": failure_receipt,
        "failure_receipts": failure_receipts,
        "memory_operation_receipt": recorder.receipt if recorder is not None else [],
        "myna_operations": (
            [row["operation"] for row in recorder.receipt if row["outcome"] == "succeeded"]
            if recorder is not None
            else []
        ),
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
        "used_memory": bool(getattr(delegate, "used_memory", False)),
    }


def _build_live_provider(spec: dict[str, Any]) -> LLMProvider:
    benchmark_root = Path(spec["benchmark_root"]).resolve()
    if str(benchmark_root) not in sys.path:
        sys.path.append(str(benchmark_root))
    from benchmarks.picobench.budget import BudgetGuardedProvider, ProviderBudgetConfig, ProviderBudgetLedger
    from pico.cli._helpers import make_provider

    provider_name = spec["provider_name"]
    config = Config()
    config.agents.defaults.model = spec["model"]
    config.agents.defaults.max_tokens = int(spec["max_output_tokens_per_call"])
    provider_config = getattr(config.providers, provider_name, None)
    if provider_config is None:
        raise ValueError("live task-effect provider is unsupported")
    provider_config.api_key = os.environ.get("PICO_BENCH_PROVIDER_API_KEY", "")
    provider_config.api_base = spec.get("provider_api_base")
    delegate = make_provider(config)
    if spec.get("disable_thinking"):
        delegate.extra_body = {**getattr(delegate, "extra_body", {}), "thinking": {"type": "disabled"}}
    budget = spec["budget"]
    ledger_config = ProviderBudgetConfig(
        hard_cap_cny=float(budget["hard_cap_cny"]),
        external_service_reserve_cny=0.0,
        max_total_request_attempts=int(budget["maximum_provider_attempts"]),
        max_input_tokens_per_call=int(spec["max_input_tokens_per_call"]),
        max_output_tokens_per_call=int(spec["max_output_tokens_per_call"]),
        input_cache_miss_usd_per_million=float(budget["input_cache_miss_usd_per_million"]),
        output_usd_per_million=float(budget["output_usd_per_million"]),
        conservative_usd_to_cny_multiplier=float(budget["conservative_usd_to_cny_multiplier"]),
        approval_digest=budget["approval_digest"],
        ledger_prefix_event_count=int(budget["ledger_prefix_event_count"]),
        ledger_prefix_digest=budget["ledger_prefix_digest"],
        ledger_prefix_charged_cny=float(budget["ledger_prefix_charged_cny"]),
    )
    return BudgetGuardedProvider(
        delegate,
        ledger=ProviderBudgetLedger(Path(budget["ledger_path"]), ledger_config),
    )


def _provider_scope(spec: dict[str, Any]):
    if spec.get("provider_mode") != "live" or "budget" not in spec:
        return contextlib.nullcontext()
    benchmark_root = Path(spec["benchmark_root"]).resolve()
    if str(benchmark_root) not in sys.path:
        sys.path.append(str(benchmark_root))
    from benchmarks.picobench.budget import provider_call_budget_scope

    return provider_call_budget_scope(
        trial_id=spec["trial_id"],
        max_logical_calls=int(spec["max_logical_calls_per_trial"]),
        max_attempts_per_call=int(spec["max_attempts_per_call"]),
        max_input_tokens_per_call=int(spec["max_input_tokens_per_call"]),
        max_output_tokens_per_call=int(spec["max_output_tokens_per_call"]),
    )


def _provider_request_attempts(
    provider: LLMProvider,
    *,
    baseline: int = 0,
    fallback: int = 0,
) -> int:
    ledger = getattr(provider, "ledger", None)
    snapshot = getattr(ledger, "snapshot", None)
    if not callable(snapshot):
        return fallback
    return max(0, int(snapshot().request_attempts) - baseline)


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


def _provider_failure_receipt(exc: Exception) -> dict[str, Any]:
    return {
        "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
        "failure_class": _provider_exception_class(exc),
        "phase": "provider_call",
        "error": _error(exc),
    }


def _provider_exception_class(exc: Exception) -> str:
    names: set[str] = set()
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.update(klass.__name__.lower() for klass in type(current).__mro__)
        current = current.__cause__ or current.__context__
    if any("budget" in name for name in names):
        return "budget"
    if any(marker in name for name in names for marker in ("connection", "network", "timeout", "transport")):
        return "transport"
    return "provider"


def _provider_category_class(category: str) -> str:
    lowered = category.lower()
    if "budget" in lowered:
        return "budget"
    if any(marker in lowered for marker in ("connection", "network", "timeout", "transport")):
        return "transport"
    return "provider"


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
