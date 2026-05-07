"""Small runtime control plane for Pico.

The control plane owns decisions around tool pressure and final-answer gates.
It is intentionally narrow: the main runtime still calls the model and tools;
this layer only turns observed state into reminders, rejections, and final
blocking notices.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import completion


@dataclass(frozen=True)
class ControlDecision:
    action: str = "allow"
    reason: str = ""
    message: str = ""
    metadata: dict = field(default_factory=dict)
    next_tool: str = ""
    tool_args: dict = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "message": self.message,
            "metadata": dict(self.metadata or {}),
            "next_tool": self.next_tool,
            "tool_args": dict(self.tool_args or {}),
        }


class ProgressGuard:
    def before_tool(self, agent, task_state, name: str, args: dict, user_message: str) -> ControlDecision:
        tasks = agent.current_tasks()
        tool = agent.tools.get(name) or {}
        task_state.tasks = tasks
        active = next((task for task in tasks if task.get("status") == "in_progress"), None)
        pending = next((task for task in tasks if task.get("status") == "pending"), None)
        if tasks and active is None and pending and name != "todo_update":
            message = (
                "Runtime reminder: the previous task is closed but the next task has not been activated. "
                f"Next tool should update task {pending.get('id')} to in_progress before continuing."
            )
            next_tool = "todo_update"
            tool_args = {"id": str(pending.get("id", "")), "status": "in_progress"}
            if tool.get("read_only", not tool.get("risky", True)) and "pending_task_needs_activation" in getattr(agent, "_runtime_reminder_keys", set()):
                agent._last_tool_result_metadata = {
                    "tool_status": "rejected",
                    "tool_error_code": "progress_guard_stale_task",
                    "security_event_type": "",
                    "risk_level": "low",
                    "read_only": True,
                    "affected_paths": [],
                    "workspace_changed": False,
                    "diff_summary": [],
                }
                return ControlDecision(
                    action="reject",
                    reason="progress_guard_stale_task",
                    message=(
                        "error: runtime progress guard blocked this inspection because the previous reminder was ignored. "
                        + message
                    ),
                    next_tool=next_tool,
                    tool_args=tool_args,
                )
            if tool.get("read_only", not tool.get("risky", True)):
                return ControlDecision(
                    action="remind",
                    reason="pending_task_needs_activation",
                    message=message,
                    next_tool=next_tool,
                    tool_args=tool_args,
                )
        reminder = agent.runtime_tool_reminder(name, user_message, args)
        if not reminder:
            return ControlDecision()
        reason = str(reminder.get("reason", ""))
        message = str(reminder.get("message", ""))
        if reason in getattr(agent, "_runtime_reminder_keys", set()) and agent.should_enforce_runtime_reminder(reminder, name, args):
            return ControlDecision(
                action="reject",
                reason="progress_guard_stale_task",
                message=agent.runtime_reminder_rejection(reminder, name, args),
                metadata={"reminder": reminder},
            )
        return ControlDecision(action="remind", reason=reason, message=message, metadata={"reminder": reminder})


class CompletionGate:
    @staticmethod
    def _has_workspace_inspection(agent) -> bool:
        inspection_tools = {"list_files", "read_file", "glob", "grep", "search"}
        return any(
            item.get("role") == "tool" and item.get("name") in inspection_tools
            for item in getattr(agent, "session", {}).get("history", []) or []
        )

    def before_final(self, agent, task_state, proposed_final: str, user_message: str) -> ControlDecision:
        assessment = agent.assess_completion(task_state, user_message)
        warnings = list(assessment.get("warnings", []) or [])
        hard_blocks = list(assessment.get("hard_blocks", []) or [])
        if completion.expects_workspace_inspection(user_message) and not self._has_workspace_inspection(agent):
            hard_blocks.append("inspect workspace with list_files before final answer")
            warnings.append("inspect workspace with list_files before final answer")
        verification_plan = dict(getattr(task_state, "verification_plan", {}) or {})
        missing_evidence = list(verification_plan.get("missing_evidence", []) or [])
        failed_static_checks = [
            item
            for item in verification_plan.get("static_checks", []) or []
            if str(item.get("status", "")) == "failed"
        ]

        reasons = list(hard_blocks)
        for item in missing_evidence:
            requirement = str(item.get("requirement", "")).strip()
            reason = str(item.get("reason", "")).strip()
            reasons.append(f"{requirement}: {reason}" if requirement and reason else reason or requirement)
        for item in failed_static_checks:
            reasons.append(str(item.get("summary", "")))

        verification_required = completion.requires_verification(user_message)
        should_block = bool(hard_blocks or (verification_required and (missing_evidence or failed_static_checks)))
        if not should_block:
            return ControlDecision(
                metadata={
                    "assessment": {**assessment, "warnings": warnings, "hard_blocks": hard_blocks},
                    "proposed_final": proposed_final,
                }
            )

        suggestions = list(verification_plan.get("suggested_commands", []) or [])
        next_actions = [str(item.get("command", "")) for item in suggestions if str(item.get("command", "")).strip()]
        message = "Runtime gate blocked final answer: " + "; ".join(reason for reason in reasons if reason)
        next_tool = ""
        tool_args = {}
        if "inspect workspace with list_files before final answer" in hard_blocks and "list_files" in getattr(agent, "tools", {}):
            message += "\nNext action: inspect the workspace with list_files."
            next_tool = "list_files"
            tool_args = {"path": "."}
        elif next_actions:
            message += "\nSuggested next verification: " + "; ".join(next_actions[:3])
            next_tool = "run_shell"
            tool_args = {"command": next_actions[0], "timeout": 60}
        else:
            message += "\nNext action: complete or update the task ledger, then run a real verification command if files changed."
        return ControlDecision(
            action="block_final",
            reason="completion_gate_blocked",
            message=message,
            metadata={
                "assessment": {**assessment, "warnings": warnings, "hard_blocks": hard_blocks},
                "verification_plan": verification_plan,
                "proposed_final": proposed_final,
                "reasons": reasons,
            },
            next_tool=next_tool,
            tool_args=tool_args,
        )


class RuntimeControlPlane:
    def __init__(self):
        self.progress_guard = ProgressGuard()
        self.completion_gate = CompletionGate()

    def before_tool(self, agent, task_state, name: str, args: dict, user_message: str) -> ControlDecision:
        return self.progress_guard.before_tool(agent, task_state, name, args, user_message)

    def before_final(self, agent, task_state, proposed_final: str, user_message: str) -> ControlDecision:
        return self.completion_gate.before_final(agent, task_state, proposed_final, user_message)
