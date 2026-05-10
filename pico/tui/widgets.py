from __future__ import annotations

import json
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Markdown, Static

from ..commands.slash import SlashCommand, suggest_commands


def format_tool_args(name: str, args: dict | None) -> str:
    args = args or {}
    if name == "run_shell":
        return str(args.get("command", ""))
    if name in {"read_file", "write_file", "patch_file", "list_files"}:
        path = str(args.get("path", "."))
        if name == "write_file":
            return f"{path} ({len(str(args.get('content', '')))} chars)"
        return path
    if name == "search":
        return f"{args.get('pattern', '')} in {args.get('path', '.')}"
    if name == "delegate":
        return str(args.get("task", ""))
    return json.dumps(args, ensure_ascii=False, sort_keys=True)


PICO_CAT = [
    "        /\\___/\\",
    "       (  o o  )",
    "       /   ^   \\",
    "      /|       |\\",
]


class WelcomeBanner(Static):
    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        margin: 1 1 0 1;
        padding: 1 2;
        background: #171720;
        color: #f4f1ff;
        border: round #6c47b2;
    }
    """

    def __init__(self, model_name: str = "", cwd: str = "", approval: str = "") -> None:
        super().__init__()
        self.model_name = model_name
        self.cwd = cwd
        self.approval = approval

    def render(self) -> Text:
        accent = "#c79bff"
        muted = "#7f8192"
        cyan = "#6ee7ff"
        lines = [
            Text.assemble(
                Text("Pico-Cat", style=f"bold {accent}"),
                Text("  local runtime console", style=muted),
                Text("  =^._.^=", style=cyan),
            ),
            Text(""),
        ]
        for line in PICO_CAT:
            lines.append(Text(line, style=f"bold {accent}"))
        lines.extend(
            [
                Text(""),
                Text.assemble(
                    Text("model ", style=muted),
                    Text(self.model_name or "-", style=cyan),
                    Text("   approval ", style=muted),
                    Text(self.approval or "-", style=cyan),
                    Text("   cwd ", style=muted),
                    Text(Path(self.cwd).name + "/" if self.cwd else "-", style=cyan),
                ),
                Text("type /help for commands, /context for budget, /trace for run evidence", style=muted),
            ]
        )
        return Text("\n").join(lines)


class UserMessage(Static):
    DEFAULT_CSS = """
    UserMessage {
        background: #162117;
        color: #8fffb0;
        border: tall #2b6d3a;
        margin: 0 0 1 0;
        padding: 0 1 0 1;
    }
    """

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    def render(self) -> Text:
        return Text.assemble(Text("> ", style="bold green"), Text(self.content, style="green"))


class AssistantMessage(Static):
    DEFAULT_CSS = """
    AssistantMessage {
        background: #171720;
        color: #f1efff;
        border: tall #2b2c3a;
        margin: 0 0 1 0;
        padding: 0 1;
        height: auto;
    }
    AssistantMessage Markdown {
        height: auto;
        width: 100%;
    }
    """

    def __init__(self, content: str) -> None:
        super().__init__(markup=False)
        self.content = content

    def compose(self):
        yield Markdown(self.content)

    def update_content(self, content: str) -> None:
        self.content = content
        try:
            self.query_one(Markdown).update(content)
        except Exception:
            pass


class ToolCard(Static):
    DEFAULT_CSS = """
    ToolCard {
        background: #171720;
        border: round #5f4aa6;
        margin: 0 0 1 0;
        padding: 0 1;
        height: auto;
    }
    ToolCard Collapsible {
        width: 1fr;
    }
    ToolCard .tool-output {
        max-height: 16;
        color: #a7a9bb;
        padding: 0 1;
        overflow-x: hidden;
    }
    """

    def __init__(self, tool_name: str, args_summary: str = "") -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args_summary = args_summary[:120]
        self.status = "running"
        self.output = ""
        self.artifact_relpath = ""
        self._collapsible: Collapsible | None = None
        self._output_widget: Static | None = None

    def compose(self):
        self._output_widget = Static("", classes="tool-output")
        self._collapsible = Collapsible(self._output_widget, title=self._label(), collapsed=False)
        yield self._collapsible

    def _label(self) -> str:
        icon = {"running": "RUN", "success": "OK", "error": "ERR"}.get(self.status, "..")
        if self.args_summary:
            return f"[{icon}] {self.tool_name}: {self.args_summary}"
        return f"[{icon}] {self.tool_name}"

    def _refresh_label(self) -> None:
        if self._collapsible is not None:
            self._collapsible.title = self._label()

    def set_running(self) -> None:
        self.status = "running"
        self._refresh_label()
        if self._collapsible is not None:
            self._collapsible.collapsed = False

    def set_success(self, output: str = "", artifact_relpath: str = "") -> None:
        self.status = "success"
        self.output = output
        self.artifact_relpath = artifact_relpath
        self._refresh_label()
        display = output
        if artifact_relpath:
            display += f"\nfull result: {artifact_relpath}"
        if len(display) > 1200:
            display = display[:1197] + "..."
        if self._output_widget is not None:
            self._output_widget.update(display)
        if self._collapsible is not None:
            self._collapsible.collapsed = True

    def set_error(self, output: str = "") -> None:
        self.status = "error"
        self.output = output
        self._refresh_label()
        if self._output_widget is not None:
            self._output_widget.update(output[:1200])
        if self._collapsible is not None:
            self._collapsible.collapsed = False

    def set_diff(self, diff_text: str) -> None:
        self.status = "success"
        self.output = diff_text
        self._refresh_label()
        if self._output_widget is not None:
            try:
                self._output_widget.update(Syntax(diff_text, "diff", theme="monokai"))
            except Exception:
                self._output_widget.update(diff_text[:1200])
        if self._collapsible is not None:
            self._collapsible.collapsed = False


class ChatLog(VerticalScroll):
    DEFAULT_CSS = """
    ChatLog {
        height: 1fr;
        scrollbar-size: 1 1;
        padding: 1 1 0 1;
        background: #101015;
    }
    """

    def add_message(self, role: str, content: str, tool_name: str = ""):
        if role == "user":
            widget = UserMessage(content)
        elif role == "assistant":
            widget = AssistantMessage(content)
        elif role == "tool":
            widget = ToolCard(tool_name=tool_name, args_summary=content)
        else:
            widget = Static(content)
        self.mount(widget)
        self.call_after_refresh(self.scroll_end, animate=False)
        return widget

    def add_tool_call(self, name: str, args: dict):
        card = ToolCard(tool_name=name, args_summary=format_tool_args(name, args))
        self.mount(card)
        self.call_after_refresh(self.scroll_end, animate=False)
        return card

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()


class ThinkingIndicator(Static):
    DEFAULT_CSS = """
    ThinkingIndicator {
        height: 1;
        margin: 0 1;
        padding: 0 1;
        color: #6ee7ff;
        background: #101015;
        display: none;
    }
    ThinkingIndicator.visible {
        display: block;
    }
    """

    SPINNER_FRAMES = [".  ", ".. ", "...", " ..", "  .", "   "]

    def __init__(self) -> None:
        super().__init__()
        self.visible = False
        self._frame = 0
        self._tool_name = ""

    def render(self) -> Text:
        frame = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
        if self._tool_name:
            return Text.assemble(
                Text(frame + " ", style="#6ee7ff"),
                Text("Running ", style="#6ee7ff"),
                Text(self._tool_name, style="bold #c79bff"),
            )
        return Text.assemble(
            Text(frame + " ", style="#6ee7ff"),
            Text("Pico-Cat Thinking", style="bold #6ee7ff"),
        )

    def show(self) -> None:
        self.visible = True
        self._tool_name = ""
        self.add_class("visible")
        self.refresh()

    def hide(self) -> None:
        self.visible = False
        self._tool_name = ""
        self.remove_class("visible")
        self.refresh()

    def set_tool(self, tool_name: str) -> None:
        self._tool_name = str(tool_name or "")
        self.visible = True
        self.add_class("visible")
        self.refresh()

    def advance(self) -> None:
        self._frame += 1
        self.refresh()


class MessageInput(Input):
    class Submit(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    @property
    def text(self) -> str:
        return self.value

    @text.setter
    def text(self, value: str) -> None:
        self.value = value

    def action_submit(self) -> None:
        text = self.value.strip()
        if text:
            self.post_message(self.Submit(text))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.post_message(self.Submit(text))
        event.stop()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_submit()
            event.prevent_default()
            event.stop()


class SlashSuggestions(Static):
    DEFAULT_CSS = """
    SlashSuggestions {
        display: none;
        height: auto;
        max-height: 8;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #111827;
        color: #d8dcff;
        border: round #4b61a8;
    }
    SlashSuggestions.visible {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.suggestions: list[SlashCommand] = []
        self.selected_index = 0
        self.visible = False

    def update_suggestions(self, suggestions: list[SlashCommand], selected_index: int = 0) -> None:
        self.suggestions = list(suggestions)
        self.selected_index = max(0, min(int(selected_index or 0), max(len(self.suggestions) - 1, 0)))
        self.visible = bool(self.suggestions)
        self.set_class(self.visible, "visible")
        self.refresh()

    def hide_suggestions(self) -> None:
        self.update_suggestions([])

    def render(self) -> Text:
        if not self.suggestions:
            return Text("")
        lines = []
        for index, command in enumerate(self.suggestions):
            marker = ">" if index == self.selected_index else " "
            style = "bold cyan" if index == self.selected_index else "#a7a9bb"
            lines.append(
                Text.assemble(
                    Text(f"{marker} /{command.name:<10}", style=style),
                    Text(command.description, style="#d8dcff"),
                )
            )
        return Text("\n").join(lines)


class InputBar(Widget):
    DEFAULT_CSS = """
    InputBar {
        height: auto;
        min-height: 3;
        max-height: 10;
        background: #171720;
        border: round #4b61a8;
        margin: 0 1 1 1;
        padding: 0 1;
    }
    InputBar MessageInput {
        background: #0f1015;
        color: #f4f1ff;
        border: none;
        height: auto;
        min-height: 1;
        max-height: 7;
    }
    """

    class MessageSubmitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    class CommandSubmitted(Message):
        def __init__(self, command: str, args: str = "") -> None:
            self.command = command
            self.args = args
            super().__init__()

    class CancelRequested(Message):
        pass

    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []
        self.history_index = 0
        self.saved_draft = ""
        self.busy = False
        self._slash_suggestions: list[SlashCommand] = []
        self._slash_index = 0

    def compose(self):
        yield MessageInput(placeholder="Ask Pico-Cat to inspect, edit, test...", id="chat-input")
        yield SlashSuggestions()

    @property
    def input(self) -> MessageInput:
        return self.query_one("#chat-input", MessageInput)

    def on_message_input_submit(self, event: MessageInput.Submit) -> None:
        text = event.text
        self.history.append(text)
        self.history_index = len(self.history)
        self.input.text = ""
        self.hide_slash_suggestions()
        if text.startswith("/"):
            command, _, args = text[1:].partition(" ")
            self.post_message(self.CommandSubmitted(command, args.strip()))
        else:
            self.post_message(self.MessageSubmitted(text))

    def on_input_changed(self, event: Input.Changed) -> None:
        self.update_slash_suggestions(event.value)

    def on_key(self, event: Key) -> None:
        if event.key == "tab" and self._slash_suggestions:
            self.complete_slash_suggestion()
            event.prevent_default()
            event.stop()
        elif event.key == "up" and self._slash_suggestions:
            self._move_slash_selection(-1)
            event.prevent_default()
            event.stop()
        elif event.key == "down" and self._slash_suggestions:
            self._move_slash_selection(1)
            event.prevent_default()
            event.stop()
        elif event.key == "up":
            self._navigate_history(-1)
            event.prevent_default()
        elif event.key == "down":
            self._navigate_history(1)
            event.prevent_default()
        elif event.key == "escape":
            if self._slash_suggestions:
                self.hide_slash_suggestions()
            else:
                self.post_message(self.CancelRequested())
            event.prevent_default()

    def update_slash_suggestions(self, text: str | None = None) -> None:
        text = self.input.text if text is None else str(text)
        self._slash_suggestions = suggest_commands(text)
        self._slash_index = 0
        self.query_one(SlashSuggestions).update_suggestions(self._slash_suggestions, self._slash_index)

    def hide_slash_suggestions(self) -> None:
        self._slash_suggestions = []
        self._slash_index = 0
        self.query_one(SlashSuggestions).hide_suggestions()

    def complete_slash_suggestion(self) -> None:
        if not self._slash_suggestions:
            return
        command = self._slash_suggestions[self._slash_index]
        raw = self.input.text
        _, separator, rest = raw[1:].partition(" ") if raw.startswith("/") else ("", "", "")
        suffix = rest if separator else ""
        self.input.text = f"/{command.name} " + (suffix if suffix else "")
        self.input.cursor_position = len(self.input.text)
        self.hide_slash_suggestions()

    def _move_slash_selection(self, direction: int) -> None:
        if not self._slash_suggestions:
            return
        self._slash_index = (self._slash_index + direction) % len(self._slash_suggestions)
        self.query_one(SlashSuggestions).update_suggestions(self._slash_suggestions, self._slash_index)

    def _navigate_history(self, direction: int) -> None:
        if not self.history:
            return
        if direction == -1 and self.history_index == len(self.history):
            self.saved_draft = self.input.text
        new_index = self.history_index + direction
        if new_index < 0 or new_index > len(self.history):
            return
        self.history_index = new_index
        if self.history_index == len(self.history):
            self.input.text = self.saved_draft
        else:
            self.input.text = self.history[self.history_index]

    def set_busy(self, busy: bool) -> None:
        self.busy = bool(busy)
        self.input.disabled = self.busy
        if not self.busy:
            self.input.focus()

    def focus_input(self) -> None:
        self.input.focus()


class ConfirmPrompt(Static):
    DEFAULT_CSS = """
    ConfirmPrompt {
        background: #211817;
        border: round #d79a4a;
        margin: 0 0 1 0;
        padding: 0 1;
        height: auto;
    }
    """

    def __init__(self, tool_name: str, args_summary: str = "") -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args_summary = args_summary
        self.selected = True

    def render(self) -> Text:
        approval = "ALLOW" if self.selected else "DENY"
        style = "bold green" if self.selected else "bold red"
        lines = [
            Text.assemble(Text(self.tool_name, style="bold yellow"), Text(" needs approval")),
            Text(self.args_summary[:240], style="dim"),
            Text(f"[{approval}] y allow / n deny / left-right switch / enter confirm", style=style),
        ]
        return Text("\n").join(lines)

    def select_allow(self) -> None:
        self.selected = True
        self.refresh()

    def select_deny(self) -> None:
        self.selected = False
        self.refresh()


class StatusBar(Widget):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: #171720;
        color: #6ee7ff;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.model_name = ""
        self.step_count = 0
        self.approval_policy = ""
        self.session_id = ""
        self.context_tokens = 0
        self.window_tokens = 0
        self.runtime_mode = ""
        self.stage = ""
        self.tasks_completed = 0
        self.tasks_total = 0
        self.verify_status = "not_run"
        self.gate_status = ""
        self.subagent_count = 0
        self.cwd = ""
        self.logo = "=^._.^= PICO"

    def render(self) -> Text:
        parts = []
        if self.model_name:
            parts.append(self.model_name)
        parts.append(f"Step {self.step_count}")
        if self.context_tokens:
            parts.append(f"ctx {self.context_tokens}/{self.window_tokens}")
        if self.runtime_mode and self.runtime_mode != "execute":
            parts.append(f"mode {self.runtime_mode}")
        if self.stage:
            parts.append(f"stage {self.stage}")
        if self.tasks_total:
            parts.append(f"tasks {self.tasks_completed}/{self.tasks_total}")
        if self.verify_status and self.verify_status != "not_run":
            parts.append(f"verify {self.verify_status}")
        if self.gate_status:
            parts.append(f"gate {self.gate_status}")
        if self.subagent_count:
            parts.append(f"agents {self.subagent_count}")
        if self.approval_policy:
            parts.append(f"approval {self.approval_policy}")
        if self.session_id:
            parts.append(f"session {self.session_id[:8]}")
        if self.cwd:
            parts.append(Path(self.cwd).name + "/")
        parts.append(self.logo)
        return Text(" | ".join(parts), style="#6ee7ff")

    def update_agent(self, agent) -> None:
        self.model_name = str(getattr(agent.model_client, "model", ""))
        self.approval_policy = str(agent.approval_policy)
        self.session_id = str(agent.session.get("id", ""))
        self.cwd = str(agent.root)
        self.runtime_mode = str(getattr(agent, "runtime_mode", "execute"))
        self.update_progress(agent, refresh=False)
        self.refresh()

    def update_steps(self, count: int) -> None:
        self.step_count = int(count)
        self.refresh()

    def update_context_usage(self, usage: dict) -> None:
        self.context_tokens = int(usage.get("estimated_prompt_tokens") or 0)
        self.window_tokens = int(usage.get("model_context_window_tokens") or 0)
        self.refresh()

    def update_progress(self, agent, refresh: bool = True) -> None:
        task_state = getattr(agent, "current_task_state", None)
        self.runtime_mode = str(getattr(agent, "runtime_mode", "execute"))
        self.stage = str(getattr(task_state, "stage", "") or "")
        tasks = []
        if task_state is not None:
            tasks = list(getattr(task_state, "tasks", []) or [])
        if not tasks:
            tasks = list(getattr(agent, "session", {}).get("tasks", []) or [])
        self.tasks_total = len(tasks)
        self.tasks_completed = sum(1 for task in tasks if task.get("status") == "completed")
        if hasattr(agent, "verification_status"):
            self.verify_status = str(agent.verification_status())
        else:
            self.verify_status = "not_run"
        gate = dict(getattr(task_state, "completion_gate", {}) or {}) if task_state is not None else {}
        self.gate_status = "blocked" if gate.get("blocked") else str(gate.get("status", "") or "")
        if self.gate_status in {"running", "completed"}:
            self.gate_status = ""
        self.subagent_count = len(getattr(agent, "session", {}).get("subagents", []) or [])
        manager = getattr(agent, "subagent_manager", None)
        if manager is not None:
            self.subagent_count = max(self.subagent_count, len(manager.running_status()))
        if refresh:
            self.refresh()
