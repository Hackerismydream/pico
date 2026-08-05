"""Tool registry for dynamic tool management."""

import asyncio
from typing import Any

from pico.agent.tools.base import Tool, ToolResult
from pico.tracing import semconv, trace


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    # Backstop ceiling for tools that don't set their own ``timeout_seconds``.
    # Generous on purpose: it exists to break an infinite hang (a tool with no
    # internal timeout that never returns), not to enforce a tight per-tool SLA.
    DEFAULT_TOOL_TIMEOUT_S = 300.0

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    @trace.instrument("tool.call", extract=semconv.tool_call)
    async def execute(self, name: str, params: dict[str, Any], call_id: str | None = None) -> ToolResult:
        """Execute a tool by name with given parameters.

        ``call_id`` is the model's own tool-call id when the caller has one; it
        is not used for dispatch, only recorded as ``tool.call_id`` so the span
        joins the ToolEvent the same call emits.
        """
        _hint = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}",
                failed=True,
            )

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)

            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return ToolResult(
                    f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _hint,
                    failed=True,
                )

            ceiling = tool.timeout_seconds or self.DEFAULT_TOOL_TIMEOUT_S
            if tool.blocking_interaction:
                # Intentionally waits on a human — must not be timer-killed.
                result = await tool.execute(**params)
            else:
                result = await asyncio.wait_for(tool.execute(**params), timeout=ceiling)

            if isinstance(result, ToolResult):
                return result
            if isinstance(result, str) and result.startswith("Error"):
                return ToolResult(result + _hint, failed=True)
            return ToolResult(result)
        except asyncio.TimeoutError:
            return ToolResult(
                f"Error: Tool '{name}' timed out after {ceiling:.0f}s." + _hint,
                failed=True,
            )
        except Exception as e:
            return ToolResult(f"Error executing {name}: {str(e)}" + _hint, failed=True)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
