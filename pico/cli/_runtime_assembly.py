"""Shared construction and resource ownership for the three Runtime hosts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from pico.agent.loop.recovery import limits_from_defaults

if TYPE_CHECKING:
    from pico.agent.loop import AgentLoop
    from pico.config.paths import RuntimePaths
    from pico.config.pico import PicoConfig
    from pico.config.schema import Config
    from pico.context_engine.factory import ContextEngineFactory
    from pico.memory_engine import MemoryBackend
    from pico.session.manager import SessionManager


@dataclass
class RuntimeAssembly:
    agent_loop: AgentLoop
    session_manager: SessionManager
    backend: MemoryBackend | None
    _backend_start_attempted: bool = field(default=False, init=False)
    _backend_started: bool = field(default=False, init=False)
    _backend_start_error: BaseException | None = field(default=None, init=False)
    _agent_closed: bool = field(default=False, init=False)
    _backend_stopped: bool = field(default=False, init=False)

    async def start_memory_backend(self) -> bool:
        if self.backend is None:
            return True
        if self._backend_start_attempted:
            if self._backend_start_error is not None:
                raise self._backend_start_error
            return self._backend_started
        self._backend_start_attempted = True
        try:
            await self.backend.start()
        except BaseException as exc:
            self._backend_start_error = exc
            raise
        self._backend_started = True
        return True

    async def close(self) -> None:
        cancellation: BaseException | None = None
        if not self._agent_closed:
            agent_error: BaseException | None = None
            try:
                _stop_agent_skill_watcher(self.agent_loop)
            except Exception as exc:
                logger.exception(
                    "local Skill watcher close failed; continuing shutdown",
                )
                agent_error = exc
            except BaseException as exc:
                cancellation = exc

            try:
                await self.agent_loop.close_mcp()
            except Exception as exc:
                logger.exception(
                    "agent runtime close failed; continuing shutdown",
                )
                if agent_error is None:
                    agent_error = exc
            except BaseException as exc:
                if cancellation is None:
                    cancellation = exc
            if agent_error is None and cancellation is None:
                self._agent_closed = True

        backend_error: BaseException | None = None
        if self.backend is None:
            self._backend_stopped = True
        elif not self._backend_stopped:
            try:
                await self.backend.stop()
            except BaseException as exc:
                logger.exception(
                    "memory backend stop failed after agent shutdown",
                )
                backend_error = exc
            else:
                self._backend_stopped = True

        if cancellation is not None:
            raise cancellation
        if backend_error is not None:
            raise backend_error


def _stop_agent_skill_watcher(agent_loop: Any) -> None:
    """Stop the Local Skill watcher owned by the Agent's ContextBuilder.

    Older test doubles and third-party AgentLoop-compatible objects may expose
    only ``close_mcp``. Treat the watcher hook as optional for those objects,
    while the concrete Pico AgentLoop always provides ``context.skills``.
    """
    context = getattr(agent_loop, "context", None)
    skills = getattr(context, "skills", None)
    stop = getattr(skills, "stop_file_watcher", None)
    if callable(stop):
        stop()


def assemble_runtime(
    config: Config,
    pico_config: PicoConfig,
    *,
    provider: Any,
    cron_service: Any,
    interactive: bool,
    router: Any = None,
    session_manager: SessionManager | None = None,
    context_engine_factory: "ContextEngineFactory | None" = None,
    paths: "RuntimePaths | None" = None,
) -> RuntimeAssembly:
    from pico.agent.loop import AgentLoop
    from pico.cli._plugin_stack import (
        build_plugin_registry,
        build_plugin_tools,
        maybe_build_memory_backend,
    )
    from pico.config.paths import RuntimePaths
    from pico.session.manager import SessionManager

    paths = paths or RuntimePaths(
        workspace=config.workspace_path,
        state=config.workspace_path,
    )
    if session_manager is None:
        session_manager = SessionManager(paths.state)
    plugin_registry = build_plugin_registry(pico_config)
    backend = maybe_build_memory_backend(
        paths.workspace,
        pico_config,
        registry=plugin_registry,
    )
    plugin_tools = build_plugin_tools(
        paths.workspace,
        pico_config,
        registry=plugin_registry,
    )
    defaults = config.agents.defaults
    agent_loop = AgentLoop(
        provider=provider,
        workspace=paths.workspace,
        state=paths.state,
        model=defaults.model,
        max_iterations=defaults.max_tool_iterations,
        empty_recovery=limits_from_defaults(defaults),
        context_window_tokens=defaults.context_window_tokens,
        max_concurrent_subagents=defaults.max_concurrent_subagents,
        max_subagent_spawns_per_hour=defaults.max_subagent_spawns_per_hour,
        brave_api_key=config.tools.web.search.api_key or None,
        jina_api_key=config.tools.web.jina_api_key or None,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron_service,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        disabled_tools=config.tools.disabled_tools,
        tool_search_config=config.tools.tool_search,
        sandbox_config=config.tools.sandbox,
        channels_config=config.channels,
        router=router,
        skill_forge_config=pico_config.skill_forge,
        context_config=pico_config.context,
        context_engine_factory=context_engine_factory,
        runtime_config=pico_config.runtime,
        interactive=interactive,
        backend=backend,
        memory_config=pico_config.memory,
        skill_forge_router_config=pico_config.skill_forge.router,
        plugin_tools=plugin_tools,
    )
    agent_loop.configure_personalization(
        defaults.enable_personalization,
    )
    return RuntimeAssembly(
        agent_loop=agent_loop,
        session_manager=session_manager,
        backend=backend,
    )


__all__ = ["RuntimeAssembly", "assemble_runtime"]
