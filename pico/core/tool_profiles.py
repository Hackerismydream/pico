"""Named tool capability surfaces for runtime modes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSetProfile:
    name: str
    allowed_tools: frozenset[str]

    def allows(self, tool_name):
        return tool_name in self.allowed_tools


def build_tool_profiles(tools):
    all_tools = frozenset(tools)
    coordinator_tools = frozenset({"agent", "send_message", "task_stop"})
    read_only = frozenset(name for name, tool in tools.items() if tool.read_only) - coordinator_tools
    plan_tools = read_only | frozenset({"write_file", "patch_file", "agent", "send_message", "task_stop"})
    worker_tools = all_tools - coordinator_tools - frozenset({"run_shell"})
    return {
        "default": ToolSetProfile("default", all_tools),
        "plan": ToolSetProfile("plan", plan_tools & all_tools),
        "readonly": ToolSetProfile("readonly", read_only),
        "worker": ToolSetProfile("worker", worker_tools),
    }
