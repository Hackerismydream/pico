from __future__ import annotations

import asyncio
import re
import threading
from functools import partial

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Key

from ..commands.slash import command_help_markdown, parse_skill_args, parse_subagent_args, resolve_command
from ..features.verifier_driver import select_verification_action
from .widgets import ChatLog, ConfirmPrompt, InputBar, StatusBar, ThinkingIndicator, ToolCard, WelcomeBanner, format_tool_args


HELP_TEXT = command_help_markdown()


def _display_verification_command(command: str) -> str:
    return re.sub(r"(?:\S*/)?python\d*(?=\s+-)", "python", str(command or ""), count=1)


PICO_TUI_CSS = """
Screen {
    layout: vertical;
    background: #101015;
}
"""


class PicoTuiApp(App):
    CSS = PICO_TUI_CSS
    BINDINGS = [
        Binding("enter", "submit_input", "Send", priority=True, show=False),
        Binding("ctrl+l", "clear_screen", "Clear"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self._previous_event_callback = getattr(agent, "event_callback", None)
        self._previous_approval_callback = getattr(agent, "approval_callback", None)
        self._cancel_event = threading.Event()
        self._running_tool_cards: list[ToolCard] = []
        self._confirm_prompt: ConfirmPrompt | None = None
        self._confirm_decision: tuple[threading.Event, dict] | None = None
        self._turn_count = 0
        self._suppress_subagent_runtime_event = False
        self._install_runtime_hooks()

    def compose(self) -> ComposeResult:
        yield WelcomeBanner(
            model_name=str(getattr(self.agent.model_client, "model", "")),
            cwd=str(getattr(self.agent, "root", "")),
            approval=str(getattr(self.agent, "approval_policy", "")),
        )
        yield ChatLog()
        yield ThinkingIndicator()
        yield StatusBar()
        yield InputBar()

    def on_mount(self) -> None:
        self.query_one(StatusBar).update_agent(self.agent)
        self.query_one(InputBar).focus_input()
        self.set_interval(0.25, self._drain_subagent_notifications)

    def _install_runtime_hooks(self) -> None:
        self.agent.event_callback = self._runtime_event_callback
        self.agent.approval_callback = self._approval_callback

    def _runtime_event_callback(self, event: dict) -> None:
        if self._previous_event_callback is not None:
            try:
                self._previous_event_callback(event)
            except Exception:
                pass
        try:
            self.call_from_thread(self._handle_runtime_event, dict(event))
        except Exception:
            pass

    def _approval_callback(self, name: str, args: dict, metadata: dict) -> bool:
        if self._previous_approval_callback is not None:
            return bool(self._previous_approval_callback(name, args, metadata))
        decision_event = threading.Event()
        decision = {"approved": False}
        try:
            self.call_from_thread(self._show_confirm, name, args, decision_event, decision)
        except Exception:
            return False
        decision_event.wait()
        return bool(decision.get("approved", False))

    def _show_confirm(self, name: str, args: dict, event: threading.Event, decision: dict) -> None:
        chat = self.query_one(ChatLog)
        prompt = ConfirmPrompt(name, format_tool_args(name, args))
        self._confirm_prompt = prompt
        self._confirm_decision = (event, decision)
        chat.mount(prompt)
        chat.call_after_refresh(chat.scroll_end, animate=False)

    def _resolve_confirm(self, approved: bool) -> None:
        if self._confirm_decision is None:
            return
        event, decision = self._confirm_decision
        decision["approved"] = bool(approved)
        event.set()
        if self._confirm_prompt is not None:
            self._confirm_prompt.remove()
        self._confirm_prompt = None
        self._confirm_decision = None

    def on_key(self, event: Key) -> None:
        if self._confirm_prompt is not None:
            if event.key in {"y", "enter"}:
                self._resolve_confirm(self._confirm_prompt.selected)
                event.prevent_default()
            elif event.key == "n":
                self._resolve_confirm(False)
                event.prevent_default()
            elif event.key == "left":
                self._confirm_prompt.select_deny()
                event.prevent_default()
            elif event.key == "right":
                self._confirm_prompt.select_allow()
                event.prevent_default()
            elif event.key == "escape":
                self._resolve_confirm(False)
                event.prevent_default()

    def action_submit_input(self) -> None:
        if self._confirm_prompt is not None:
            self._resolve_confirm(self._confirm_prompt.selected)
            return
        bar = self.query_one(InputBar)
        text = bar.input.text.strip()
        if not text:
            return
        bar.history.append(text)
        bar.history_index = len(bar.history)
        bar.input.text = ""
        bar.hide_slash_suggestions()
        if text.startswith("/"):
            command, _, args = text[1:].partition(" ")
            self._handle_command(command, args.strip())
            return
        self.query_one(ChatLog).add_message("user", text)
        self._run_agent(text)

    def on_input_bar_message_submitted(self, event: InputBar.MessageSubmitted) -> None:
        chat = self.query_one(ChatLog)
        chat.add_message("user", event.text)
        self._run_agent(event.text)

    def on_input_bar_command_submitted(self, event: InputBar.CommandSubmitted) -> None:
        self._handle_command(event.command, event.args)

    def on_input_bar_cancel_requested(self, event: InputBar.CancelRequested) -> None:
        if self._confirm_prompt is not None:
            self._resolve_confirm(False)
            return
        self._cancel_event.set()

    def _run_agent(self, text: str) -> None:
        self._cancel_event.clear()
        self.query_one(InputBar).set_busy(True)
        self.query_one(ThinkingIndicator).show()
        self._thinking_timer = self.set_interval(0.15, self.query_one(ThinkingIndicator).advance)
        asyncio.create_task(self._agent_task(text))

    async def _agent_task(self, text: str) -> None:
        loop = asyncio.get_running_loop()
        chat = self.query_one(ChatLog)
        try:
            result = await loop.run_in_executor(None, partial(self.agent.ask, text, self._cancel_event))
        except Exception as exc:
            chat.add_message("assistant", f"[Error] {exc}")
            self.query_one(InputBar).set_busy(False)
            self._stop_thinking()
            return
        chat.add_message("assistant", result)
        self._turn_count += 1
        status = self.query_one(StatusBar)
        status.update_steps(self._turn_count)
        status.update_progress(self.agent)
        if self.agent.last_prompt_metadata.get("context_usage"):
            status.update_context_usage(self.agent.last_prompt_metadata["context_usage"])
        self.query_one(InputBar).set_busy(False)
        self._stop_thinking()

    def _stop_thinking(self) -> None:
        timer = getattr(self, "_thinking_timer", None)
        if timer is not None:
            timer.stop()
            self._thinking_timer = None
        self.query_one(ThinkingIndicator).hide()

    def _handle_runtime_event(self, event: dict) -> None:
        name = str(event.get("event", ""))
        if name == "prompt_built":
            usage = (event.get("prompt_metadata") or {}).get("context_usage") or {}
            if usage:
                self.query_one(StatusBar).update_context_usage(usage)
            return
        if name == "tool_started":
            tool_name = str(event.get("name", ""))
            self.query_one(ThinkingIndicator).set_tool(tool_name)
            args = event.get("args") if isinstance(event.get("args"), dict) else {}
            card = self.query_one(ChatLog).add_tool_call(tool_name, args)
            self._running_tool_cards.append(card)
            return
        if name == "tool_finished":
            self._finish_tool_card(event)
            self.query_one(StatusBar).update_progress(self.agent)
            return
        if name in {"subagent_started", "subagent_completed", "subagent_failed", "subagent_killed"}:
            if self._suppress_subagent_runtime_event:
                self.query_one(StatusBar).update_progress(self.agent)
                return
            subagent = dict(event.get("subagent", {}) or {})
            self.query_one(ChatLog).add_message("assistant", self._subagent_text(subagent))
            self.query_one(StatusBar).update_progress(self.agent)
            return
        if name in {"task_list_updated", "stage_changed", "verification_recorded", "completion_gate_blocked", "run_finished"}:
            self.query_one(StatusBar).update_progress(self.agent)
            return

    def _finish_tool_card(self, event: dict) -> None:
        tool_name = str(event.get("name", ""))
        card = None
        for candidate in reversed(self._running_tool_cards):
            if candidate.tool_name == tool_name and candidate.status == "running":
                card = candidate
                break
        if card is None:
            card = self.query_one(ChatLog).add_tool_call(tool_name, event.get("args") or {})
        result = str(event.get("result", ""))
        status = str(event.get("tool_status", "ok"))
        if status in {"error", "rejected", "partial_success"}:
            card.set_error(result)
            return
        diff_summary = event.get("diff_summary") or []
        if diff_summary:
            card.set_success("\n".join(str(item) for item in diff_summary), artifact_relpath=str(event.get("artifact_relpath", "")))
            return
        card.set_success(result, artifact_relpath=str(event.get("artifact_relpath", "")))

    def _handle_command(self, command: str, args: str) -> None:
        chat = self.query_one(ChatLog)
        raw_command = str(command).strip()
        if raw_command.startswith("skill:"):
            payload, error = parse_skill_args(f"{raw_command} {args}".strip())
            if error:
                chat.add_message("assistant", error)
                return
            message = self._skill_invocation_text(payload)
            chat.add_message("user", message)
            self._run_agent(message)
            return
        resolved = resolve_command(raw_command)
        command = resolved.name if resolved is not None else raw_command
        args = str(args or "").strip()
        if command == "help":
            chat.add_message("assistant", HELP_TEXT)
        elif command == "clear":
            self.action_clear_screen()
        elif command == "new":
            self.agent.reset()
            self._turn_count = 0
            self.query_one(StatusBar).update_steps(0)
            chat.clear_messages()
            chat.add_message("assistant", "Started a new Pico session.")
        elif command == "memory":
            chat.add_message("assistant", self.agent.memory_text())
        elif command == "session":
            chat.add_message(
                "assistant",
                f"Session: `{self.agent.session_path}`\n\nEvents: `{self.agent.session_store.event_path(self.agent.session['id'])}`",
            )
        elif command == "context":
            chat.add_message("assistant", self._context_text())
        elif command == "trace":
            chat.add_message("assistant", self._trace_text())
        elif command == "tasks":
            chat.add_message("assistant", self._tasks_text())
        elif command == "verify":
            chat.add_message("assistant", self._verify_text())
        elif command == "agents":
            chat.add_message("assistant", self._agents_text())
        elif command == "subagent":
            chat.add_message("assistant", self._start_subagent_text(args))
        elif command == "skills":
            chat.add_message("assistant", self._skills_text())
        elif command == "skill":
            payload, error = parse_skill_args(args)
            if error:
                chat.add_message("assistant", error)
                return
            message = self._skill_invocation_text(payload)
            chat.add_message("user", message)
            self._run_agent(message)
        elif command == "history":
            chat.add_message("assistant", self._history_text())
        elif command == "resume":
            chat.add_message("assistant", self._resume_session(args))
        elif command == "compact":
            chat.add_message("assistant", self._compact_text(args))
        elif command == "plan":
            message, follow_up = self._enter_plan_text(args)
            chat.add_message("assistant", message)
            if follow_up:
                chat.add_message("user", f"Plan request: {args}")
                self._run_agent(follow_up)
        elif command in {"execute", "exit-plan"}:
            chat.add_message("assistant", self._exit_plan_text())
        elif command == "approval":
            self._set_approval(args)
        else:
            chat.add_message("assistant", f"Unknown command: /{raw_command}. Type /help.")

    @staticmethod
    def _skill_invocation_text(payload: dict) -> str:
        name = str(payload.get("name", "")).strip()
        args = str(payload.get("args", "")).strip()
        return f"/skill:{name}" + (f" {args}" if args else "")

    def _skills_text(self) -> str:
        if hasattr(self.agent, "feature_enabled") and not self.agent.feature_enabled("skills"):
            return "Available skills: disabled."
        skills = [skill for skill in self.agent.skill_catalog.discover() if skill.user_invocable]
        if not skills:
            return "Available skills: none."
        lines = ["# Available skills", ""]
        for skill in skills:
            command = skill.command_name()
            if skill.argument_hint:
                command += f" <{skill.argument_hint}>"
            desc = skill.description or "(no description)"
            detail = f" — {skill.when_to_use}" if skill.when_to_use else ""
            lines.append(f"- `{command}` — {desc}{detail}")
        diagnostics = list(getattr(self.agent.skill_catalog, "last_diagnostics", []) or [])
        if diagnostics:
            lines.extend(["", "## Diagnostics"])
            for item in diagnostics:
                lines.append(f"- {item.get('type', 'warning')}: {item.get('message', item)}")
        return "\n".join(lines)

    def _start_subagent_text(self, args: str) -> str:
        payload, error = parse_subagent_args(args)
        if error:
            return error
        try:
            result = self.agent.subagent_manager.spawn(**payload)
            if result.get("status") == "started":
                self.agent.record_subagent_started(result)
            else:
                self.agent.deliver_subagent_notification(result)
        except Exception as exc:
            return f"[Error] {exc}"
        self.query_one(StatusBar).update_progress(self.agent)
        task_id = str(result.get("task_id", ""))
        subagent_type = str(result.get("subagent_type", payload.get("subagent_type", "")))
        description = str(result.get("description", payload.get("description", "")))
        return f"Started subagent `{task_id}` [{subagent_type}]: {description}"

    def _drain_subagent_notifications(self) -> None:
        manager = getattr(self.agent, "subagent_manager", None)
        if manager is None:
            return
        notifications = manager.drain_notifications()
        if not notifications:
            return
        chat = self.query_one(ChatLog)
        for notification in notifications:
            self._suppress_subagent_runtime_event = True
            try:
                delivered = self.agent.deliver_subagent_notification(notification)
            finally:
                self._suppress_subagent_runtime_event = False
            chat.add_message("assistant", self._subagent_text(dict(delivered.get("subagent", notification) or {})))
        self.query_one(StatusBar).update_progress(self.agent)

    @staticmethod
    def _subagent_text(subagent: dict) -> str:
        status = str(subagent.get("status", ""))
        desc = str(subagent.get("description", "subagent"))
        task_id = str(subagent.get("task_id", ""))
        result = str(subagent.get("result", "")).strip()
        error = str(subagent.get("error", "")).strip()
        lines = [f"Subagent `{task_id}` {status}: {desc}"]
        if error:
            lines.extend(["", error])
        elif result:
            lines.extend(["", result])
        return "\n".join(lines)

    def _set_approval(self, args: str) -> None:
        chat = self.query_one(ChatLog)
        if args not in {"auto", "ask", "never"}:
            chat.add_message("assistant", "Usage: /approval auto|ask|never")
            return
        self.agent.approval_policy = args
        self.query_one(StatusBar).update_agent(self.agent)
        chat.add_message("assistant", f"Approval policy set to `{args}`.")

    def _context_text(self) -> str:
        usage = self.agent.last_prompt_metadata.get("context_usage") or {}
        if not usage:
            return "Context usage: no prompt has been built yet."
        lines = [
            "# Context usage",
            f"- estimated prompt tokens: {usage.get('estimated_prompt_tokens', 0)}",
            f"- model window: {usage.get('model_context_window_tokens', 0)}",
            f"- reserved output: {usage.get('reserved_output_tokens', 0)}",
            f"- status: {usage.get('budget_status', '-')}",
            "",
            "## Sections",
        ]
        for section, tokens in sorted((usage.get("section_estimated_tokens") or {}).items()):
            lines.append(f"- {section}: {tokens}")
        return "\n".join(lines)

    def _trace_text(self) -> str:
        task_state = self.agent.current_task_state
        if task_state is None:
            return "No run trace yet."
        trace_path = self.agent.run_store.trace_path(task_state)
        report_path = self.agent.run_store.report_path(task_state)
        return f"Trace: `{trace_path}`\n\nReport: `{report_path}`"

    def _tasks_text(self) -> str:
        return self.agent.run_tool("todo_list", {})

    def _verify_text(self) -> str:
        task_state = self.agent.current_task_state
        plan = dict(getattr(task_state, "verification_plan", {}) or {}) if task_state is not None else {}
        verifications = []
        if task_state is not None:
            verifications = list(task_state.verifications or [])
        if not verifications:
            verifications = list(self.agent.session.get("verifications", []) or [])
        lines = ["# Verification artifacts"]
        if plan:
            lines.append("\n## Plan")
            for item in plan.get("requirements", []) or []:
                lines.append(f"- requirement `{item.get('id', '')}` — {item.get('reason', '')}")
            for item in plan.get("suggested_commands", []) or []:
                lines.append(f"- suggested `{item.get('command', '')}` — {item.get('reason', '')}")
            for item in plan.get("missing_evidence", []) or []:
                lines.append(f"- missing `{item.get('requirement', '')}` — {item.get('reason', '')}")
            action = select_verification_action(plan)
            if action:
                action_args = action.get("args", {})
                lines.append(f"- next action `{action.get('name', '')}` — {action_args.get('command', '')}")
        graph = dict(getattr(task_state, "artifact_graph", {}) or {}) if task_state is not None else {}
        artifacts = list(graph.get("artifacts", []) or [])
        if artifacts:
            lines.append("\n## Artifact status")
            for item in artifacts[-10:]:
                lines.append(f"- [{item.get('status', '')}] `{item.get('kind', '')}` {item.get('path', '')}")
        if not verifications:
            lines.append("\nVerification artifacts: none")
            return "\n".join(lines)
        lines.append("\n## Artifacts")
        for item in verifications[-10:]:
            command = _display_verification_command(item.get("command", ""))
            lines.append(
                f"- [{item.get('status', 'not_run')}] exit={item.get('exit_code', '-')} "
                f"`{command}` — {item.get('summary', '')}"
            )
        return "\n".join(lines)

    def _agents_text(self) -> str:
        subagents = list(self.agent.session.get("subagents", []) or [])
        lines = ["# Subagents"]
        running = []
        manager = getattr(self.agent, "subagent_manager", None)
        if manager is not None:
            running = manager.running_status()
        if running:
            lines.append("\n## Running")
            for item in running:
                lines.append(
                    f"- `{item.get('task_id', '')}` [{item.get('subagent_type', '')}] "
                    f"{item.get('description', '')} — {item.get('activity', '') or 'running'}"
                )
        if not subagents:
            if not running:
                lines.append("\nNo subagents yet.")
            return "\n".join(lines)
        lines.append("\n## Recent")
        for item in subagents[-20:]:
            usage = dict(item.get("usage", {}) or {})
            result = str(item.get("result", "")).strip().replace("\n", " ")
            if len(result) > 160:
                result = result[:157] + "..."
            lines.append(
                f"- `{item.get('task_id', '')}` [{item.get('status', '')}] "
                f"{item.get('subagent_type', '')} {item.get('description', '')} "
                f"tools={usage.get('tool_uses', 0)} {result}"
            )
        return "\n".join(lines)

    def _history_text(self) -> str:
        sessions = self.agent.session_store.list_sessions()
        if not sessions:
            return "Session history: no saved sessions."
        lines = ["# Session history"]
        for index, session in enumerate(sessions[:20], start=1):
            current = " current" if session["id"] == self.agent.session["id"] else ""
            lines.append(
                f"- {index}. `{session['id']}`{current} "
                f"messages={session['history_count']} mode={session['runtime_mode']} updated={session['updated_at']}"
            )
        return "\n".join(lines)

    def _resolve_session_id(self, query: str) -> str:
        query = str(query or "").strip()
        sessions = self.agent.session_store.list_sessions()
        if not query:
            return ""
        try:
            index = int(query) - 1
            if 0 <= index < len(sessions):
                return sessions[index]["id"]
        except ValueError:
            pass
        matches = [session["id"] for session in sessions if session["id"].startswith(query)]
        return matches[0] if len(matches) == 1 else ""

    def _resume_session(self, args: str) -> str:
        session_id = self._resolve_session_id(args)
        if not session_id:
            return "Usage: /resume <session-id|number>. Run /history first."
        self.agent.load_session(session_id)
        self._turn_count = 0
        self.query_one(StatusBar).update_agent(self.agent)
        self.query_one(StatusBar).update_steps(0)
        return f"Resumed session `{session_id}`."

    def _compact_text(self, args: str) -> str:
        keep_recent = 6
        if args:
            try:
                keep_recent = int(args)
            except ValueError:
                return "Usage: /compact [recent-message-count]"
        result = self.agent.compact_history(keep_recent=keep_recent)
        if not result["compacted"]:
            return "Compact skipped: too few messages."
        return (
            "Compacted history: "
            f"{result['before_messages']} -> {result['after_messages']} messages, "
            f"~{result['before_tokens']} -> ~{result['after_tokens']} tokens."
        )

    def _enter_plan_text(self, args: str) -> tuple[str, str]:
        if self.agent.runtime_mode == "plan":
            plan_path = self.agent.active_plan_path()
            self.query_one(StatusBar).update_agent(self.agent)
            if args:
                return (
                    "Already in plan mode.\n\n"
                    f"Plan file: `{plan_path}`\n\n"
                    "Continuing with your planning request.",
                    self._plan_follow_up_prompt(args),
                )
            return (self._current_plan_text(plan_path), "")
        plan_path = self.agent.enter_plan_mode(args)
        self.query_one(StatusBar).update_agent(self.agent)
        message = (
            "Entered plan mode.\n\n"
            f"Plan file: `{plan_path}`\n\n"
            "Project file edits are blocked until `/execute`."
        )
        if args:
            message += "\n\nStarting the planning request now."
            return (message, self._plan_follow_up_prompt(args))
        message += "\n\nUse `/plan <task>` or type a planning request next."
        return (message, "")

    def _current_plan_text(self, plan_path) -> str:
        if plan_path is None:
            return "Plan mode is active, but no plan file is attached."
        try:
            content = plan_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            return f"Plan mode is active, but the plan file could not be read: {exc}"
        if content:
            return f"Current plan: `{plan_path}`\n\n{content}"
        return f"Plan mode active, but no plan has been written yet.\n\nPlan file: `{plan_path}`"

    def _plan_follow_up_prompt(self, args: str) -> str:
        plan_path = self.agent.active_plan_path()
        return (
            "We are in plan mode. Do not edit project files.\n"
            f"User planning request: {args}\n\n"
            f"Write the plan into the active plan file: {plan_path}\n"
            "You may inspect the workspace first if needed. Produce a concise final summary in chat after writing the plan."
        )

    def _exit_plan_text(self) -> str:
        if self.agent.runtime_mode != "plan":
            return "Not in plan mode."
        plan_text = self.agent.exit_plan_mode()
        self.query_one(StatusBar).update_agent(self.agent)
        if plan_text.strip():
            return "Exited plan mode.\n\nApproved plan:\n" + plan_text
        return "Exited plan mode. No plan text was written."

    def action_clear_screen(self) -> None:
        self.query_one(ChatLog).clear_messages()

    def action_quit(self) -> None:
        self.exit()
