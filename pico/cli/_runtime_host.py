"""Ready-first lifecycle for the TUI's Runtime Assembly."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pico.cli._runtime_assembly import RuntimeAssembly


class TuiRuntimeHost:
    """Build the Runtime Assembly off the TUI-RPC event loop."""

    def __init__(self, build: "Callable[[], RuntimeAssembly]") -> None:
        self._build = build
        self._task: asyncio.Task[RuntimeAssembly] | None = None
        self._runtime: RuntimeAssembly | None = None
        self._closed = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._build_runtime())

    async def acquire(self) -> "RuntimeAssembly":
        self.start()
        task = self._task
        if task is None:
            raise RuntimeError("TUI Runtime Host failed to start")
        return await asyncio.shield(task)

    def get_now(self) -> "RuntimeAssembly | None":
        return self._runtime

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._task is None:
            return
        try:
            runtime = await asyncio.shield(self._task)
        except Exception:
            return
        await runtime.close()

    async def _build_runtime(self) -> "RuntimeAssembly":
        runtime = await asyncio.to_thread(self._build)
        self._runtime = runtime
        return runtime


__all__ = ["TuiRuntimeHost"]
