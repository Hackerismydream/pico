"""Agent 运行时核心逻辑。

Pico 就是包在模型外面的控制循环：负责组 prompt、解析模型输出、
校验并执行工具、写 trace、更新工作记忆，以及在合适的时候停下来。
"""

import json
import os
import queue
import re
import textwrap
import threading
import uuid
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..features import completion
from ..features import memory as memorylib
from ..features.artifacts import build_artifact_graph
from ..features.compact import CompactService, deterministic_summary
from ..features.context_manager import ContextManager
from ..features.context_usage import build_context_usage
from ..features.control import RuntimeControlPlane
from ..features.plan_mode import PlanModeController
from ..features.skill_runtime import SkillRuntime
from ..features.skills import SkillCatalog, parse_skill_command
from ..features.subagents import SubagentManager
from ..features.verifier_driver import build_verification_plan
from ..providers.adapter import is_recoverable_error, is_truncated
from ..providers.base import CompletionResult
from ..tools import registry as toolkit
from ..tools.registry import is_allowed
from ..tools.shell_safety import is_read_only_shell_command
from .model_decision import (
    ModelDecisionAdapter,
    extract as extract_decision_tag,
    extract_raw as extract_raw_decision_tag,
    parse_attrs as parse_decision_attrs,
    parse_model_output,
    parse_xml_tool as parse_xml_model_tool,
    retry_notice as model_retry_notice,
    strip_cdata as strip_model_cdata,
)
from .policy_engine import PolicyEngine, ToolRequest
from .run_context import RunContext
from .run_lifecycle import RunLifecycle
from .run_store import RunStore
from .runtime_engine import CompletionTurnResult, RunRequest, RuntimeEngine
from .runtime_events import RuntimeEvents
from .runtime_snapshot import RuntimeSnapshot
from .session import SessionStore
from .task_state import TaskState
from .tool_policy import ToolPolicyController
from .tool_runner import ToolExecutionContext, ToolRunner
from .workspace import IGNORED_PATH_NAMES, MAX_HISTORY, WorkspaceContext, clip, now

SENSITIVE_ENV_NAME_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
REDACTED_VALUE = "<redacted>"
DEFAULT_SHELL_ENV_ALLOWLIST = ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "LOGNAME", "PATH", "PWD", "SHELL", "TERM", "TMPDIR", "TMP", "TEMP", "USER")
DEFAULT_FEATURE_FLAGS = {
    "memory": True,
    "relevant_memory": True,
    "context_reduction": True,
    "auto_compact": True,
    "prompt_cache": True,
    "skills": True,
}
CHECKPOINT_SCHEMA_VERSION = "phase1-v1"
RUNTIME_MODE_EXECUTE = "execute"
RUNTIME_MODE_PLAN = "plan"
CHECKPOINT_NONE_STATUS = "no-checkpoint"
CHECKPOINT_FULL_VALID_STATUS = "full-valid"
CHECKPOINT_PARTIAL_STALE_STATUS = "partial-stale"
CHECKPOINT_WORKSPACE_MISMATCH_STATUS = "workspace-mismatch"
CHECKPOINT_SCHEMA_MISMATCH_STATUS = "schema-mismatch"
DURABLE_MEMORY_INTENT_PATTERN = re.compile(r"(?i)\b(capture|remember|save|store|persist|note)\b")
DURABLE_MEMORY_INTENT_ZH_PATTERN = re.compile(r"(记住|保存|记录|沉淀|长期记忆|持久记忆)")
DURABLE_MEMORY_LINE_PATTERNS = (
    ("project-conventions", re.compile(r"(?i)^Project convention:\s*(.+)$")),
    ("key-decisions", re.compile(r"(?i)^Decision:\s*(.+)$")),
    ("dependency-facts", re.compile(r"(?i)^Dependency:\s*(.+)$")),
    ("user-preferences", re.compile(r"(?i)^Preference:\s*(.+)$")),
    ("project-conventions", re.compile(r"^项目约定：\s*(.+)$")),
    ("key-decisions", re.compile(r"^决策：\s*(.+)$")),
    ("dependency-facts", re.compile(r"^依赖：\s*(.+)$")),
    ("user-preferences", re.compile(r"^偏好：\s*(.+)$")),
)
SECRET_SHAPED_TEXT_PATTERN = re.compile(r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})")
@dataclass
class PromptPrefix:
    # prefix 除了文本本身，还带一小份元数据，
    # 这样 runtime 才能明确判断 prefix 是否可以复用。
    text: str
    hash: str
    workspace_fingerprint: str
    tool_signature: str
    skill_signature: str
    built_at: str


class Pico:
    def __init__(
        self,
        model_client,
        workspace,
        session_store,
        session=None,
        run_store=None,
        approval_policy="ask",
        max_steps=6,
        max_new_tokens=512,
        depth=0,
        max_depth=1,
        read_only=False,
        shell_env_allowlist=None,
        secret_env_names=None,
        feature_flags=None,
        allowed_tools=None,
        skill_roots=None,
        event_callback=None,
        approval_callback=None,
        write_scope=None,
    ):
        self.model_client = model_client
        self.workspace = workspace
        self.root = Path(workspace.repo_root)
        self.session_store = session_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.max_new_tokens = max_new_tokens
        self.read_only_stall_limit = 4
        self.depth = depth
        self.max_depth = max_depth
        self.read_only = read_only
        self.allowed_tools = tuple(str(name) for name in allowed_tools) if allowed_tools is not None else None
        self.write_scope = tuple(str(path) for path in (write_scope or ()))
        self.event_callback = event_callback
        self.approval_callback = approval_callback
        self.shell_env_allowlist = tuple(shell_env_allowlist or DEFAULT_SHELL_ENV_ALLOWLIST)
        self.secret_env_names = {str(name).upper() for name in (secret_env_names or ())}
        self.feature_flags = dict(DEFAULT_FEATURE_FLAGS)
        if feature_flags:
            self.feature_flags.update({str(key): bool(value) for key, value in feature_flags.items()})
        self.run_store = run_store or RunStore(Path(workspace.repo_root) / ".pico" / "runs")
        self.session = session or {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "created_at": now(),
            "workspace_root": workspace.repo_root,
            "history": [],
            "memory": memorylib.default_memory_state(),
        }
        self._ensure_session_shape()
        self.memory = memorylib.LayeredMemory(
            self.session.setdefault("memory", memorylib.default_memory_state()),
            workspace_root=self.root,
        )
        self.session["memory"] = self.memory.to_dict()
        self.skill_catalog = SkillCatalog(self.root, skill_roots=skill_roots)
        self.skill_loader = self.skill_catalog
        self.skill_runtime = SkillRuntime(self, self.skill_catalog)
        self.plan_mode_controller = PlanModeController(self.root)
        self.current_skill_invocations = []
        self.last_skill_metadata = {"selected": [], "selected_count": 0, "invoked": []}
        self.current_turn_id = ""
        self._turn_skill_event_keys = set()
        self._runtime_reminder_keys = set()
        self._trace_sequence = 0
        self._tool_artifact_sequence = 0
        self.runtime_control = RuntimeControlPlane()
        self.runtime_engine = RuntimeEngine()
        self.run_lifecycle = RunLifecycle()
        self.policy_engine = PolicyEngine()
        self.tool_policy_controller = ToolPolicyController()
        self.decision_adapter = ModelDecisionAdapter()
        self.subagent_manager = SubagentManager({
            "Explore": self._build_explore_subagent_runner(),
            "Worker": self._build_worker_subagent_runner(),
        })
        self.tools = self.build_tools()
        self.prefix_state = self.build_prefix()
        self.prefix = self.prefix_state.text
        self.context_manager = ContextManager(self)
        self.compact_service = CompactService(
            model_client=self.model_client,
            model_name=str(getattr(self.model_client, "model", "")),
        )
        self.resume_state = self.evaluate_resume_state()
        self.session_path = self.session_store.save(self.session)
        self.session_event_path = self.session_store.event_path(self.session["id"])
        if not self.session_event_path.exists() or self.session_event_path.stat().st_size == 0:
            self.append_session_event(
                "session_started",
                {
                    "workspace_root": self.workspace.repo_root,
                    "runtime_identity": self.current_runtime_identity(),
                },
            )
        self.current_task_state = None
        self.current_run_dir = None
        self.last_prompt_metadata = {}
        self.last_completion_metadata = {}
        self.last_durable_promotions = []
        self.last_durable_rejections = []
        self.last_durable_superseded = []
        self._last_tool_result_metadata = {}
        self._last_prefix_refresh = {
            "workspace_changed": False,
            "prefix_changed": False,
        }

    @classmethod
    def from_session(cls, model_client, workspace, session_store, session_id, **kwargs):
        return cls(
            model_client=model_client,
            workspace=workspace,
            session_store=session_store,
            session=session_store.load(session_id),
            **kwargs,
        )

    def _ensure_session_shape(self):
        self.session.setdefault("history", [])
        self.session.setdefault("memory", memorylib.default_memory_state())
        checkpoints = self.session.setdefault("checkpoints", {})
        if not isinstance(checkpoints, dict):
            checkpoints = {}
            self.session["checkpoints"] = checkpoints
        checkpoints.setdefault("current_id", "")
        checkpoints.setdefault("items", {})
        runtime_identity = self.session.setdefault("runtime_identity", {})
        if not isinstance(runtime_identity, dict):
            self.session["runtime_identity"] = {}
        resume_state = self.session.setdefault("resume_state", {})
        if not isinstance(resume_state, dict):
            self.session["resume_state"] = {}
        tool_policy = self.session.setdefault("tool_policy", {})
        if not isinstance(tool_policy, dict):
            tool_policy = {}
            self.session["tool_policy"] = tool_policy
        tool_policy.setdefault("read_ledger", {})
        runtime_mode = self.session.setdefault("runtime_mode", {})
        if not isinstance(runtime_mode, dict):
            runtime_mode = {}
            self.session["runtime_mode"] = runtime_mode
        runtime_mode.setdefault("mode", RUNTIME_MODE_EXECUTE)
        runtime_mode.setdefault("plan_file", "")
        runtime_mode.setdefault("topic", "")
        runtime_mode.setdefault("entered_at", "")
        tasks = self.session.setdefault("tasks", [])
        if not isinstance(tasks, list):
            self.session["tasks"] = []
        verifications = self.session.setdefault("verifications", [])
        if not isinstance(verifications, list):
            self.session["verifications"] = []
        subagents = self.session.setdefault("subagents", [])
        if not isinstance(subagents, list):
            self.session["subagents"] = []
        compaction = self.session.setdefault("compaction", {})
        if not isinstance(compaction, dict):
            compaction = {}
            self.session["compaction"] = compaction
        compaction.setdefault("compact_count", 0)
        compaction.setdefault("last_compacted_at", "")
        compaction.setdefault("last_summary_chars", 0)
        compaction.setdefault("last_summary_source", "")
        compaction.setdefault("last_trigger", "")
        compaction.setdefault("last_before_tokens", 0)
        compaction.setdefault("last_after_tokens", 0)
        compaction.setdefault("last_error", "")
        self.session.setdefault("session_schema_version", "session-v2")

    def current_runtime_identity(self):
        return {
            "session_id": self.session.get("id", ""),
            "cwd": str(self.root),
            "model": str(getattr(self.model_client, "model", "")),
            "model_client": self.model_client.__class__.__name__,
            "approval_policy": self.approval_policy,
            "read_only": bool(self.read_only),
            "max_steps": int(self.max_steps),
            "max_new_tokens": int(self.max_new_tokens),
            "feature_flags": dict(self.feature_flags),
            "allowed_tools": list(self.allowed_tools) if self.allowed_tools is not None else None,
            "shell_env_allowlist": list(self.shell_env_allowlist),
            "workspace_fingerprint": getattr(getattr(self, "prefix_state", None), "workspace_fingerprint", self.workspace.fingerprint()),
            "tool_signature": self.tool_signature(),
            "skill_signature": self.skill_signature(),
            "runtime_mode": self.runtime_mode,
        }

    def checkpoint_state(self):
        self._ensure_session_shape()
        return self.session["checkpoints"]

    def current_checkpoint(self):
        state = self.checkpoint_state()
        checkpoint_id = str(state.get("current_id", "")).strip()
        if not checkpoint_id:
            return None
        return state.get("items", {}).get(checkpoint_id)

    def invalidate_stale_memory(self):
        invalidated = self.memory.invalidate_stale_file_summaries()
        self.session["memory"] = self.memory.to_dict()
        return invalidated

    def evaluate_resume_state(self):
        previous_resume_state = dict(self.session.get("resume_state", {}) or {})
        invalidated = self.invalidate_stale_memory()
        checkpoint = self.current_checkpoint()
        status = CHECKPOINT_NONE_STATUS
        stale_paths = list(invalidated)
        mismatch_fields = []
        if checkpoint:
            if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
                status = CHECKPOINT_SCHEMA_MISMATCH_STATUS
            else:
                for item in checkpoint.get("key_files", []):
                    path = str(item.get("path", "")).strip()
                    if not path:
                        continue
                    expected = item.get("freshness")
                    current = memorylib.file_freshness(path, self.root)
                    if expected != current and path not in stale_paths:
                        stale_paths.append(path)
                saved_identity = dict(checkpoint.get("runtime_identity", {}) or self.session.get("runtime_identity", {}) or {})
                current_identity = self.current_runtime_identity()
                identity_keys = (
                    "cwd",
                    "model",
                    "model_client",
                    "approval_policy",
                    "read_only",
                    "max_steps",
                    "max_new_tokens",
                    "feature_flags",
                    "allowed_tools",
                    "shell_env_allowlist",
                    "workspace_fingerprint",
                    "tool_signature",
                    "skill_signature",
                    "runtime_mode",
                )
                for key in identity_keys:
                    if key not in saved_identity:
                        continue
                    if saved_identity.get(key) != current_identity.get(key):
                        mismatch_fields.append(key)
                mismatch_fields.sort()
                if stale_paths:
                    status = CHECKPOINT_PARTIAL_STALE_STATUS
                elif mismatch_fields:
                    status = CHECKPOINT_WORKSPACE_MISMATCH_STATUS
                else:
                    status = CHECKPOINT_FULL_VALID_STATUS

        resume_state = {
            "status": status,
            "stale_paths": stale_paths,
            "runtime_identity_mismatch_fields": mismatch_fields,
            "stale_summary_invalidations": max(
                len(invalidated),
                int(previous_resume_state.get("stale_summary_invalidations", 0))
                if status == CHECKPOINT_PARTIAL_STALE_STATUS
                else 0,
            ),
        }
        self.session["resume_state"] = resume_state
        self.session["runtime_identity"] = self.current_runtime_identity()
        return resume_state

    def render_checkpoint_text(self):
        checkpoint = self.current_checkpoint()
        if not checkpoint:
            return ""
        lines = [
            "Task checkpoint:",
            f"- Resume status: {self.resume_state.get('status', CHECKPOINT_NONE_STATUS)}",
            f"- Current goal: {checkpoint.get('current_goal', '-') or '-'}",
            f"- Current blocker: {checkpoint.get('current_blocker', '-') or '-'}",
            f"- Next step: {checkpoint.get('next_step', '-') or '-'}",
        ]
        key_files = [str(item.get("path", "")).strip() for item in checkpoint.get("key_files", []) if str(item.get("path", "")).strip()]
        lines.append(f"- Key files: {', '.join(key_files) or '-'}")
        if checkpoint.get("completed"):
            lines.append("- Completed: " + " | ".join(str(item) for item in checkpoint.get("completed", [])))
        if checkpoint.get("excluded"):
            lines.append("- Excluded: " + " | ".join(str(item) for item in checkpoint.get("excluded", [])))
        if self.resume_state.get("stale_paths"):
            lines.append("- Stale paths: " + ", ".join(self.resume_state["stale_paths"]))
        summary = str(checkpoint.get("summary", "")).strip()
        if summary:
            lines.append(f"- Summary: {summary}")
        return "\n".join(lines)

    @staticmethod
    def remember(bucket, item, limit):
        if not item:
            return
        if item in bucket:
            bucket.remove(item)
        bucket.append(item)
        del bucket[:-limit]

    def build_tools(self):
        return toolkit.build_tool_registry(self)

    def _build_explore_subagent_runner(self):
        def run(task, prompt, cancel_event):
            child = task.state.get("child")
            if child is None:
                child = Pico(
                    model_client=self.model_client,
                    workspace=self.workspace,
                    session_store=self.session_store,
                    run_store=self.run_store,
                    approval_policy="never",
                    max_steps=8,
                    max_new_tokens=self.max_new_tokens,
                    depth=self.depth + 1,
                    max_depth=self.max_depth,
                    read_only=True,
                    shell_env_allowlist=self.shell_env_allowlist,
                    secret_env_names=self.secret_env_names,
                    feature_flags=self.feature_flags,
                    allowed_tools=("list_files", "read_file", "glob", "grep", "search", "run_shell", "todo_list"),
                    skill_roots=None,
                )
                task.state["child"] = child
            child.session["memory"]["task"] = prompt
            answer = child.ask(prompt, cancel_event=cancel_event)
            state = child.current_task_state
            return {
                "status": "killed" if cancel_event.is_set() else "completed",
                "result": self._subagent_result_text(child, answer),
                "run_id": getattr(state, "run_id", ""),
                "tool_uses": int(getattr(state, "tool_steps", 0) or 0),
            }

        return run

    def _build_worker_subagent_runner(self):
        def run(task, prompt, cancel_event):
            child = task.state.get("child")
            if child is None:
                max_steps = int(getattr(task, "max_steps", 0) or 16)
                child = Pico(
                    model_client=self.model_client,
                    workspace=self.workspace,
                    session_store=self.session_store,
                    run_store=self.run_store,
                    approval_policy="auto",
                    max_steps=max_steps,
                    max_new_tokens=self.max_new_tokens,
                    depth=self.depth + 1,
                    max_depth=self.max_depth,
                    read_only=False,
                    shell_env_allowlist=self.shell_env_allowlist,
                    secret_env_names=self.secret_env_names,
                    feature_flags=self.feature_flags,
                    allowed_tools=(
                        "list_files",
                        "read_file",
                        "glob",
                        "grep",
                        "search",
                        "ask_user",
                        "write_file",
                        "write_files",
                        "patch_file",
                        "todo_write",
                        "todo_update",
                        "todo_list",
                    ),
                    skill_roots=None,
                    write_scope=getattr(task, "write_scope", []),
                )
                task.state["child"] = child
            child.session["memory"]["task"] = prompt
            answer = child.ask(prompt, cancel_event=cancel_event)
            state = child.current_task_state
            return {
                "status": "killed" if cancel_event.is_set() else "completed",
                "result": self._subagent_result_text(child, answer),
                "run_id": getattr(state, "run_id", ""),
                "tool_uses": int(getattr(state, "tool_steps", 0) or 0),
            }

        return run

    @staticmethod
    def _subagent_result_text(child, answer):
        errors = []
        for item in child.session.get("history", []):
            if item.get("role") != "tool":
                continue
            content = str(item.get("content", ""))
            if content.startswith("error:"):
                errors.append(content)
        if not errors:
            return str(answer)
        return str(answer).rstrip() + "\n\nTool errors:\n" + "\n".join(errors[-5:])

    @property
    def runtime_mode(self):
        return self.plan_mode_controller.mode(self.session)

    def active_plan_path(self):
        return self.plan_mode_controller.active_plan_path(self.session, self.path)

    def active_plan_relpath(self):
        return self.plan_mode_controller.active_plan_relpath(self.session, self.path)

    def active_plan_has_content(self):
        return self.plan_mode_controller.active_plan_has_content(self.session, self.path)

    def plans_dir(self):
        return self.plan_mode_controller.plans_dir()

    def enter_plan_mode(self, topic=""):
        topic = str(topic or "").strip()
        plan_path = self.plan_mode_controller.enter(self.session, topic)
        self.session_path = self.session_store.save(self.session)
        self.refresh_prefix(force=True)
        self.append_session_event("runtime_mode_changed", {"mode": RUNTIME_MODE_PLAN, "plan_file": self.active_plan_relpath(), "topic": topic})
        return plan_path

    def exit_plan_mode(self):
        plan_text, previous_plan = self.plan_mode_controller.exit(self.session, self.path)
        self.session_path = self.session_store.save(self.session)
        self.refresh_prefix(force=True)
        self.append_session_event("runtime_mode_changed", {"mode": RUNTIME_MODE_EXECUTE, "previous_plan_file": previous_plan})
        return plan_text

    def plan_mode_text(self):
        return self.plan_mode_controller.prompt_section(self.session, self.path)

    def tool_signature(self):
        payload = []
        for name in sorted(self.tools):
            tool = self.tools[name]
            payload.append(
                {
                    "name": name,
                    "schema": tool["schema"],
                    "risky": tool["risky"],
                    "read_only": tool.get("read_only", not tool["risky"]),
                    "activity": tool.get("activity", ""),
                    "description": tool["description"],
                    "policy": tool.get("policy", {}),
                }
            )
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def skill_signature(self):
        return self.skill_catalog.signature()

    def build_prefix(self):
        skill_signature = self.skill_signature()
        skill_count = len(self.skill_catalog.discover())
        tool_lines = []
        for name, tool in self.tools.items():
            fields = ", ".join(f"{key}: {value}" for key, value in tool["schema"].items())
            risk = "approval required" if tool["risky"] else "safe"
            policy = tool.get("policy", {})
            policy_bits = []
            if policy.get("requires_prior_read"):
                policy_bits.append("requires prior read_file")
            policy_bits.append(f"{policy.get('concurrency', 'serial')}")
            policy_text = ", ".join(policy_bits)
            tool_lines.append(f"- {name}({fields}) [{risk}; {policy_text}] {tool['description']}")
        tool_text = "\n".join(tool_lines)
        plan_text = self.plan_mode_text()
        examples = "\n".join(
            [
                '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>',
                '<tool>{"name":"glob","args":{"pattern":"**/*.py","path":"."}}</tool>',
                '<tool>{"name":"grep","args":{"pattern":"class Pico","path":"pico","glob":"*.py"}}</tool>',
                '<tool name="write_file" path="binary_search.py"><content>def binary_search(nums, target):\n    return -1\n</content></tool>',
                '<tool name="write_files"><file path="README.md"><content># Demo\n</content></file><file path="src/app.py"><content>print("hi")\n</content></file></tool>',
                '<tool name="patch_file" path="binary_search.py"><old_text>return -1</old_text><new_text>return mid</new_text></tool>',
                '<tool>{"name":"run_shell","args":{"command":"uv run --with pytest python -m pytest -q","timeout":20}}</tool>',
                '<tool>{"name":"ask_user","args":{"question":"Which package name should I use?"}}</tool>',
                '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Implement backend","active_form":"Implementing backend","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
                '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
                '<tool>{"name":"list_skills","args":{"query":"pytest","limit":20}}</tool>',
                '<tool>{"name":"load_skill","args":{"name":"pytest","args":"tests/test_pico.py"}}</tool>',
                '<tool>{"name":"agent","args":{"description":"Inspect runtime","prompt":"Find the runtime entry points and report file paths.","subagent_type":"Explore"}}</tool>',
                '<tool>{"name":"send_message","args":{"to":"agent-1234abcd","message":"Read pico/runtime.py and report only the ask loop."}}</tool>',
                "<final>Done.</final>",
            ]
        )
        # prefix 可以理解成 agent 的“工作手册”：
        # 它是谁、工具怎么调用、当前仓库是什么状态，都写在这里。
        text = textwrap.dedent(
            f"""\
            You are pico, a small local coding agent working inside a local repository.

            Rules:
            - Use tools instead of guessing about the workspace.
            - Skills use progressive disclosure: read the Available skills summary first, call list_skills when discovery is incomplete, then call load_skill only when a skill is relevant.
            - Do not infer full skill instructions from the summary. load_skill returns the authoritative skill body and base directory.
            - Return exactly one <tool>...</tool> or one <final>...</final>.
            - Tool calls must look like:
              <tool>{{"name":"tool_name","args":{{...}}}}</tool>
            - For write_file and patch_file with multi-line text, prefer XML style:
              <tool name="write_file" path="file.py"><content>...</content></tool>
            - For scaffolding a multi-file project, prefer write_files with a JSON files array.
              XML is safer for multi-line content:
              <tool name="write_files"><file path="README.md"><content>...</content></file></tool>
            - Keep each write_files call small: at most 3 files or about 200 lines total. Split larger projects across multiple tool calls instead of emitting a whole app in one model response.
            - Final answers must look like:
              <final>your answer</final>
            - Never invent tool results.
            - Keep answers concise and concrete.
            - Use glob for filename discovery instead of run_shell find/ls.
            - Use grep for content search instead of run_shell grep/rg.
            - Use ask_user only when a real ambiguity would otherwise produce work contrary to the user's intent. Do not use it for approval to proceed.
            - If the user asks you to create or update a specific file and the path is clear, use write_file or patch_file instead of repeatedly listing files.
            - After a successful write_file or write_files call, do not keep reading the files you just wrote unless a verification command failed. Mark the relevant todo complete, write the next batch, or run verification.
            - If a read-only tool is rejected by the runtime, your next tool must be write_file, write_files, patch_file, todo_update, or run_shell. Do not call another read-only tool.
            - If write_file or patch_file is rejected because a prior read_file is required, your next tool must be read_file for that exact path before retrying the write.
            - Before writing tests for existing code, read the implementation first.
            - When writing tests, match the current implementation unless the user explicitly asked you to change the code.
            - New files should be complete and runnable, including obvious imports.
            - Choose verification commands that exercise the behavior changed by the task, not just file existence or README text.
            - run_shell already runs in the workspace root. Do not cd into guessed paths like /home/user/workspace or /private/tmp/pico-workspace.
            - If a Python project has requirements.txt, prefer uv run --with-requirements requirements.txt ... for verification instead of pip install or bare python.
            - Do not repeat the same tool call with the same arguments if it did not help. Choose a different tool or return a final answer.
            - Required tool arguments must not be empty. Do not call read_file, glob, grep, ask_user, write_file, patch_file, run_shell, or delegate with args={{}}.
            - For multi-step, multi-file, full-stack, or verification-heavy tasks, create a task ledger with todo_write before making project file changes.
            - If the user names a required stack, keep it unless the user allowed an equivalent replacement.
            - If a task ledger has 3 or more tasks, include at least one task with verification=true.
            - Keep exactly one task in_progress while working. Mark tasks completed immediately after finishing them.
            - After changing files, run a real verification command before the final answer when the user requested tests, build, verification, or a full-stack project.
            - For projects with multiple parts, verification should cover the integration points between the parts when that is practical.
            - Use agent only for open-ended codebase exploration, independent verification, or genuinely parallel work. If you know the exact file or command, use the direct tool.
            - Explore subagents are read-only. Worker subagents require explicit write_scope and must not write outside it.
            - Subagents do not see this whole conversation. Agent prompts must be self-contained with relevant paths, constraints, and expected output.
            - Never delegate understanding: read subagent notifications, synthesize the result yourself, and decide the next step.
            - Do not sleep or poll for subagents. Their results arrive as <subagent-notification> messages.

            Tools:
            {tool_text}

            Skill catalog:
            - skills available: {skill_count}
            - skill_signature: {skill_signature}

            {plan_text}

            Valid response examples:
            {examples}

            {self.workspace.text()}
            """
        ).strip()
        return PromptPrefix(
            text=text,
            hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            workspace_fingerprint=self.workspace.fingerprint(),
            tool_signature=self.tool_signature(),
            skill_signature=skill_signature,
            built_at=now(),
        )

    def _apply_prefix_state(self, prefix_state):
        self.prefix_state = prefix_state
        self.prefix = prefix_state.text

    def refresh_prefix(self, force=False):
        previous_hash = getattr(getattr(self, "prefix_state", None), "hash", None)
        previous_workspace_fingerprint = getattr(getattr(self, "prefix_state", None), "workspace_fingerprint", None)
        previous_skill_signature = getattr(getattr(self, "prefix_state", None), "skill_signature", None)

        # 工作区事实相对稳定，所以这里按整体刷新；
        # 只有这些事实真的变化了，才重建完整 prefix。
        refreshed_workspace = WorkspaceContext.build(self.root)
        refreshed_workspace_fingerprint = refreshed_workspace.fingerprint()
        refreshed_skill_signature = self.skill_signature()
        workspace_changed = force or refreshed_workspace_fingerprint != previous_workspace_fingerprint
        skills_changed = force or refreshed_skill_signature != previous_skill_signature
        if workspace_changed:
            self.workspace = refreshed_workspace

        prefix_state = self.build_prefix() if workspace_changed or skills_changed or force or previous_hash is None else self.prefix_state
        prefix_changed = force or previous_hash != prefix_state.hash
        if prefix_changed:
            self._apply_prefix_state(prefix_state)

        self._last_prefix_refresh = {
            "workspace_changed": workspace_changed,
            "skills_changed": skills_changed,
            "prefix_changed": prefix_changed,
        }
        return dict(self._last_prefix_refresh)

    def memory_text(self):
        return self.memory.render_memory_text()

    def runtime_state_text(self):
        task_state = self.current_task_state
        if task_state is None:
            return ""
        lines = ["Runtime state:"]
        lines.append(f"- Stage: {task_state.stage}")
        tasks = self.current_tasks()
        if tasks:
            lines.append("- Task ledger:")
            for task in tasks[:12]:
                marker = " verification" if task.get("verification") else ""
                lines.append(f"  - {task['id']} [{task['status']}]{marker} {task['content']}")
        changed_paths = list(task_state.changed_paths or [])
        if changed_paths:
            lines.append("- Changed paths: " + ", ".join(changed_paths[:20]))
        graph = dict(task_state.artifact_graph or {})
        summary = graph.get("summary")
        if isinstance(summary, dict) and summary:
            lines.append("- Artifact summary: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.items())))
        api = graph.get("api")
        if isinstance(api, dict):
            backend_routes = list(api.get("backend_routes", []) or [])
            frontend_refs = list(api.get("frontend_references", []) or [])
            if backend_routes:
                lines.append("- Backend routes: " + ", ".join(backend_routes[:20]))
            if frontend_refs:
                lines.append("- Frontend API refs: " + ", ".join(frontend_refs[:20]))
        verification_plan = dict(task_state.verification_plan or {})
        suggestions = list(verification_plan.get("suggested_commands", []) or [])
        if suggestions:
            lines.append("- Suggested verification: " + "; ".join(str(item.get("command", "")) for item in suggestions[:4] if item.get("command")))
        missing_evidence = list(verification_plan.get("missing_evidence", []) or [])
        if missing_evidence:
            lines.append(
                "- Missing verification evidence: "
                + "; ".join(str(item.get("requirement", "")) for item in missing_evidence[:4] if item.get("requirement"))
            )
        active = next((task for task in tasks if task.get("status") == "in_progress"), None)
        if active:
            lines.append(f"- Active task: {active['id']} {active['active_form']}")
            metadata = dict(active.get("metadata", {}) or {})
            started_count = int(metadata.get("started_changed_path_count", len(changed_paths)) or 0)
            if len(changed_paths) > started_count:
                lines.append("- Next action pressure: this active task has file-change evidence; prefer todo_update before more inspection.")
        return "\n".join(lines)

    def compact_history(self, keep_recent=6, summary=None):
        return self._compact_history(trigger="manual", keep_recent=keep_recent, summary=summary)

    def auto_compact_history(self, prompt_metadata):
        if not self.feature_enabled("auto_compact"):
            return {"compacted": False, "reason": "disabled", "trigger": "auto"}
        should_compact, threshold_tokens, prompt_tokens = self.compact_service.should_auto_compact(prompt_metadata)
        if not should_compact:
            return {
                "compacted": False,
                "reason": "under_threshold",
                "trigger": "auto",
                "threshold_tokens": threshold_tokens,
                "prompt_tokens": prompt_tokens,
            }
        result = self._compact_history(trigger="auto", keep_recent=None, summary=None)
        result["threshold_tokens"] = threshold_tokens
        result["prompt_tokens"] = prompt_tokens
        return result

    def _compact_history(self, trigger, keep_recent=None, summary=None):
        history = list(self.session.get("history", []))
        result = self.compact_service.compact(
            history,
            trigger=trigger,
            keep_recent=keep_recent,
            summary=summary,
            use_model_summary=summary is None,
        )
        public_result = dict(result)
        new_history = public_result.pop("history", None)
        if not result.get("compacted"):
            return public_result

        self.session["history"] = list(new_history or [])
        compaction = self.session.setdefault("compaction", {})
        compaction["compact_count"] = int(compaction.get("compact_count", 0) or 0) + 1
        compaction["last_compacted_at"] = now()
        compaction["last_summary_chars"] = int(result.get("summary_chars", 0) or 0)
        compaction["last_summary_source"] = str(result.get("summary_source", ""))
        compaction["last_trigger"] = str(trigger)
        compaction["last_before_tokens"] = int(result.get("before_tokens", 0) or 0)
        compaction["last_after_tokens"] = int(result.get("after_tokens", 0) or 0)
        compaction["last_error"] = str(result.get("error", ""))
        self.session_path = self.session_store.save(self.session)
        self.append_session_event(
            "history_compacted",
            {
                "trigger": trigger,
                "before_messages": int(result.get("before_messages", 0) or 0),
                "after_messages": int(result.get("after_messages", 0) or 0),
                "before_tokens": int(result.get("before_tokens", 0) or 0),
                "after_tokens": int(result.get("after_tokens", 0) or 0),
                "summary_chars": int(result.get("summary_chars", 0) or 0),
                "summary_source": str(result.get("summary_source", "")),
                "error": str(result.get("error", "")),
            },
        )
        return public_result

    @staticmethod
    def build_compaction_summary(history):
        return deterministic_summary(history)

    def load_session(self, session_id):
        self.session = self.session_store.load(session_id)
        self._ensure_session_shape()
        self.memory = memorylib.LayeredMemory(
            self.session.setdefault("memory", memorylib.default_memory_state()),
            workspace_root=self.root,
        )
        self.session["memory"] = self.memory.to_dict()
        self.resume_state = self.evaluate_resume_state()
        self.session_path = self.session_store.save(self.session)
        self.session_event_path = self.session_store.event_path(self.session["id"])
        self.refresh_prefix(force=True)
        return self.session

    def history_text(self):
        history = self.session["history"]
        if not history:
            return "- empty"

        lines = []
        seen_reads = set()
        recent_start = max(0, len(history) - 6)
        for index, item in enumerate(history):
            recent = index >= recent_start
            if item["role"] == "tool" and item["name"] == "read_file" and not recent:
                path = str(item["args"].get("path", ""))
                if path in seen_reads:
                    continue
                seen_reads.add(path)

            if item["role"] == "tool":
                limit = 900 if recent else 180
                lines.append(f"[tool:{item['name']}] {json.dumps(item['args'], sort_keys=True)}")
                lines.append(clip(item["content"], limit))
            else:
                limit = 900 if recent else 220
                lines.append(f"[{item['role']}] {clip(item['content'], limit)}")

        return clip("\n".join(lines), MAX_HISTORY)

    def current_tasks(self):
        self._ensure_session_shape()
        return completion.clone_tasks(self.session.get("tasks", []) or [])

    def set_tasks(self, tasks):
        normalized = completion.normalize_tasks(tasks)
        self.session["tasks"] = normalized
        if self.current_task_state is not None:
            self.current_task_state.tasks = completion.clone_tasks(normalized)
        self.session_path = self.session_store.save(self.session)
        counts = completion.task_counts(normalized)
        self.emit_trace(
            self.current_task_state,
            "task_list_updated",
            {"tasks": normalized, "task_counts": counts},
        ) if self.current_task_state is not None else self.emit_runtime_event(
            "task_list_updated",
            {"tasks": normalized, "task_counts": counts},
        )
        return normalized

    def verification_status(self):
        task_state = self.current_task_state
        if task_state is not None:
            return completion.latest_verification_status(task_state.verifications or [])
        return completion.latest_verification_status(self.session.get("verifications", []) or [])

    def runtime_snapshot(self):
        task_state = self.current_task_state
        tasks = list(getattr(task_state, "tasks", []) or []) if task_state is not None else []
        if not tasks:
            tasks = list(self.session.get("tasks", []) or [])
        gate = dict(getattr(task_state, "completion_gate", {}) or {}) if task_state is not None else {}
        subagent_count = len(self.session.get("subagents", []) or [])
        manager = getattr(self, "subagent_manager", None)
        if manager is not None:
            subagent_count = max(subagent_count, len(manager.running_status()))
        return RuntimeSnapshot(
            model_name=str(getattr(self.model_client, "model", "")),
            approval_policy=str(self.approval_policy),
            session_id=str(self.session.get("id", "")),
            cwd=str(self.root),
            runtime_mode=str(getattr(self, "runtime_mode", RUNTIME_MODE_EXECUTE)),
            stage=str(getattr(task_state, "stage", "") or ""),
            tasks=tasks,
            verification_status=str(self.verification_status()),
            completion_gate=gate,
            subagent_count=subagent_count,
        )

    def set_stage(self, task_state, stage):
        stage = str(stage)
        if task_state.stage == stage:
            return
        previous = task_state.stage
        task_state.stage = stage
        self.emit_trace(task_state, "stage_changed", {"previous_stage": previous, "stage": stage})

    def remember_changed_paths(self, task_state, paths):
        existing = list(task_state.changed_paths or [])
        for path in paths or []:
            path = str(path)
            if path and path not in existing:
                existing.append(path)
        task_state.changed_paths = existing

    def record_verification_artifact(self, task_state, artifact):
        if not artifact:
            return
        if task_state is not None and not artifact.get("checked_paths"):
            artifact = {**dict(artifact), "checked_paths": list(task_state.changed_paths or [])}
        session_verifications = list(self.session.get("verifications", []) or [])
        session_verifications.append(dict(artifact))
        self.session["verifications"] = session_verifications[-20:]
        if task_state is not None:
            verifications = list(task_state.verifications or [])
            verifications.append(dict(artifact))
            task_state.verifications = verifications
            if artifact.get("status") == "passed":
                self.complete_open_verification_task(task_state, artifact)
            self.set_stage(task_state, "verifying" if artifact.get("status") == "passed" else "repairing")
            self.emit_trace(task_state, "verification_recorded", {"verification": artifact})
        self.session_path = self.session_store.save(self.session)

    def complete_open_verification_task(self, task_state, artifact):
        tasks = self.current_tasks()
        target_index = next(
            (
                index
                for index, task in enumerate(tasks)
                if task.get("status") == "in_progress" and completion.is_verification_task(task)
            ),
            None,
        )
        if target_index is None:
            target_index = next(
                (
                    index
                    for index, task in enumerate(tasks)
                    if task.get("status") in {"pending", "blocked"} and completion.is_verification_task(task)
                ),
                None,
            )
        if target_index is None:
            return
        task = dict(tasks[target_index])
        metadata = dict(task.get("metadata", {}) or {})
        metadata.update(
            {
                "auto_completed_by_verification": True,
                "verification_command": str(artifact.get("command", "")),
                "verification_status": str(artifact.get("status", "")),
            }
        )
        task["status"] = "completed"
        task["metadata"] = metadata
        task["updated_at"] = now()
        tasks[target_index] = task
        self.session["tasks"] = tasks
        task_state.tasks = completion.clone_tasks(tasks)
        counts = completion.task_counts(tasks)
        self.emit_trace(task_state, "task_list_updated", {"tasks": tasks, "task_counts": counts, "source": "verification_artifact"})

    def _project_file_text(self, relpath, max_chars=12000):
        try:
            path = self.root / str(relpath)
            relative_parts = path.relative_to(self.root).parts
        except ValueError:
            return ""
        if any(part in IGNORED_PATH_NAMES for part in relative_parts):
            return ""
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception:
            return ""

    def _candidate_project_paths(self, task_state, suffixes):
        suffixes = tuple(suffixes)
        paths = []
        for relpath in list(getattr(task_state, "changed_paths", []) or []):
            if str(relpath).endswith(suffixes):
                paths.append(str(relpath))
        if paths:
            return paths[:80]
        discovered = []
        for path in self.root.rglob("*"):
            try:
                relative = path.relative_to(self.root)
            except ValueError:
                continue
            if any(part in IGNORED_PATH_NAMES for part in relative.parts):
                continue
            if path.is_file() and path.suffix in suffixes:
                discovered.append(relative.as_posix())
            if len(discovered) >= 80:
                break
        return discovered

    def assess_completion(self, task_state, user_message):
        tasks = self.current_tasks()
        task_state.tasks = completion.clone_tasks(tasks)
        assessment = completion.assess_completion(
            tasks,
            task_state.verifications or [],
            task_state.changed_paths or [],
            user_message,
            workspace_changes_allowed=self.workspace_changes_allowed(),
            runtime_mode=self.runtime_mode,
            plan_artifact_written=self.active_plan_has_content(),
        )
        task_state.completion_gate = assessment
        return assessment

    def workspace_changes_allowed(self):
        if self.runtime_mode == RUNTIME_MODE_PLAN:
            return False
        if self.read_only:
            return False
        allowed_tools = set(self.allowed_tools or [])
        if not allowed_tools:
            return True
        return bool(allowed_tools & {"write_file", "patch_file", "run_shell"})

    def completion_gate(self, task_state, user_message):
        return self.assess_completion(task_state, user_message)

    def record_control_decision(self, task_state, phase, decision):
        if task_state is None or not decision or decision.action == "allow":
            return
        decisions = list(task_state.control_decisions or [])
        decisions.append(
            {
                "phase": str(phase),
                "action": decision.action,
                "reason": decision.reason,
                "message": decision.message,
                "metadata": dict(decision.metadata or {}),
                "created_at": now(),
            }
        )
        task_state.control_decisions = decisions[-50:]

    def todo_write_changes_active_status(self, args, active):
        try:
            proposed = completion.normalize_tasks((args or {}).get("todos"))
        except Exception:
            return False
        next_task = next((task for task in proposed if task.get("id") == active.get("id")), None)
        return bool(next_task and next_task.get("status") != active.get("status"))

    def tool_gate_notice(self, name, user_message, args=None):
        reminder = self.runtime_tool_reminder(name, user_message, args)
        return reminder.get("message", "") if reminder else ""

    def runtime_tool_reminder(self, name, user_message, args=None):
        if not completion.is_complex_request(user_message):
            return {}
        tasks = self.current_tasks()
        if tasks:
            if name == "todo_update":
                return {}
            active = next((task for task in tasks if task.get("status") == "in_progress"), None)
            if active and completion.requires_file_change_evidence(active):
                changed_count = len(self.current_task_state.changed_paths or []) if self.current_task_state else 0
                started_count = int((active.get("metadata") or {}).get("started_changed_path_count", changed_count) or 0)
                tool = self.tools.get(name) or {}
                if (
                    changed_count <= started_count
                    and name == "todo_write"
                    and not self.todo_write_changes_active_status(args, active)
                ):
                    return {
                        "reason": "todo_rewrite_without_progress",
                        "message": (
                            "Runtime reminder: avoid rewriting the task ledger as a substitute for progress. "
                            "The in-progress task still has no file evidence; prefer write_file, write_files, or patch_file next."
                        ),
                    }
                if (
                    changed_count <= started_count
                    and tool.get("read_only", not tool.get("risky", True))
                    and self.read_only_batches_since_last_task_update() >= 2
                ):
                    return {
                        "reason": "implementation_needs_file_evidence",
                        "message": (
                            "Runtime reminder: the current implementation task has no file evidence yet. "
                            "Prefer making a concrete file change next instead of continuing inspection."
                        ),
                    }
                if (
                    changed_count > started_count
                    and self.write_batches_since_last_task_update() >= 2
                    and not (name == "todo_write" and self.todo_write_changes_active_status(args, active))
                ):
                    return {
                        "reason": "task_status_stale",
                        "message": (
                            "Runtime reminder: the in-progress task already has file-change evidence. "
                            "Consider marking it completed or blocked before continuing."
                        ),
                    }
            return {}
        if name == "todo_write":
            return {}
        tool = self.tools.get(name) or {}
        prior_non_todo_tools = [
            item for item in self.session.get("history", [])
            if item.get("role") == "tool" and item.get("name") not in {"todo_write", "todo_update", "todo_list"}
        ]
        if len(prior_non_todo_tools) >= 2:
            return {
                "reason": "todo_missing_after_exploration",
                "message": (
                    "Runtime reminder: this looks like a multi-step task. "
                    "Create or update a task ledger soon so the work stays trackable."
                ),
            }
        if not tool.get("risky", False):
            return {}
        return {
            "reason": "missing_task_ledger",
            "message": (
                "Runtime reminder: this is a project-changing task without a task ledger yet. "
                "A todo_write plan would make the remaining work and verification easier to track."
            ),
        }

    def write_batches_since_last_task_update(self):
        count = 0
        for item in reversed(self.session.get("history", [])):
            if item.get("role") != "tool":
                continue
            if item.get("name") in {"todo_write", "todo_update"}:
                break
            if item.get("name") in {"write_file", "write_files", "patch_file"}:
                count += 1
        return count

    def read_only_batches_since_last_task_update(self):
        count = 0
        for item in reversed(self.session.get("history", [])):
            if item.get("role") != "tool":
                continue
            if item.get("name") in {"todo_write", "todo_update"}:
                break
            tool = self.tools.get(item.get("name", ""))
            if tool and tool.get("read_only", not tool.get("risky", True)):
                count += 1
        return count

    def parse_with_metadata(self, raw):
        decision = self.decision_adapter.parse(raw)
        return decision.kind, decision.payload, decision.parse_error_type

    @staticmethod
    def strip_cdata(text):
        return strip_model_cdata(text)

    def complete_model_with_deadline(self, prompt, max_new_tokens, **kwargs):
        timeout = self.model_call_timeout_seconds()
        if timeout <= 0:
            return self.model_client.complete(prompt, max_new_tokens, **kwargs)

        result_queue = queue.Queue(maxsize=1)

        def run_complete():
            try:
                result_queue.put((True, self.model_client.complete(prompt, max_new_tokens, **kwargs)))
            except BaseException as exc:
                result_queue.put((False, exc))

        worker = threading.Thread(target=run_complete, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise TimeoutError(f"model request timed out after {timeout:g}s")

        try:
            ok, value = result_queue.get_nowait()
        except queue.Empty as exc:
            raise RuntimeError("model request worker exited without returning a result") from exc
        if ok:
            return value
        raise value

    def _complete_model_turn(self, prompt, max_new_tokens, **kwargs):
        raw = self.complete_model_with_deadline(prompt, max_new_tokens, **kwargs)
        if isinstance(raw, CompletionResult):
            metadata = dict(raw.metadata or {})
            raw = raw.text
        else:
            metadata = dict(getattr(self.model_client, "last_completion_metadata", {}) or {})
        self.last_completion_metadata = metadata
        return raw, metadata

    def complete_model_turn(self, prompt, max_new_tokens, **kwargs):
        raw, metadata = self._complete_model_turn(prompt, max_new_tokens, **kwargs)
        return CompletionTurnResult(text=raw, metadata=metadata)

    def supports_prompt_cache(self):
        return bool(getattr(self.model_client, "supports_prompt_cache", False))

    def set_prompt_metadata(self, metadata):
        self.last_prompt_metadata = dict(metadata or {})
        self.last_completion_metadata = {
            key: value
            for key, value in self.last_prompt_metadata.items()
            if key in {"finish_reason", "usage", "cache", "provider", "error_type", "error_message"}
        }

    def model_error_metadata(self, exc):
        metadata = dict(getattr(self.model_client, "last_completion_metadata", {}) or {})
        metadata.setdefault("finish_reason", "error")
        metadata["error_type"] = exc.__class__.__name__
        metadata["error_message"] = str(exc)
        return metadata

    def model_call_timeout_seconds(self):
        try:
            timeout = float(getattr(self.model_client, "timeout", 0) or 0)
        except (TypeError, ValueError):
            return 0
        return timeout if timeout > 0 else 0

    @staticmethod
    def is_truncated_completion(metadata):
        return is_truncated(metadata)

    @staticmethod
    def is_recoverable_model_error(exc):
        return is_recoverable_error(exc)

    def effective_max_steps(self, user_message):
        base = int(self.max_steps)
        if completion.is_complex_request(user_message):
            return max(base, 30)
        return base

    def feature_enabled(self, name):
        return bool(self.feature_flags.get(str(name), False))

    def prompt(self, user_message):
        prompt, _ = self._build_prompt_and_metadata(user_message)
        return prompt

    def record(self, item):
        item = dict(item)
        item.setdefault("created_at", now())
        if self.current_turn_id:
            item.setdefault("turn_id", self.current_turn_id)
        if self.current_task_state is not None:
            item.setdefault("run_id", self.current_task_state.run_id)
            item.setdefault("task_id", self.current_task_state.task_id)
        item.setdefault("event_id", "hist_" + uuid.uuid4().hex[:10])
        self.session["history"].append(item)
        self.session_path = self.session_store.save(self.session)
        self.append_session_event_for_record(item)

    def write_task_state(self, task_state):
        self.run_store.write_task_state(task_state)

    @staticmethod
    def now_text():
        return now()

    def before_tool(self, task_state, name, args, user_message):
        return self.runtime_control.before_tool(self, task_state, name, args, user_message)

    def before_final(self, task_state, final, user_message):
        return self.runtime_control.before_final(self, task_state, final, user_message)

    def runtime_reminder_once(self, reason):
        reminder_key = str(reason)
        if not reminder_key or reminder_key in self._runtime_reminder_keys:
            return False
        self._runtime_reminder_keys.add(reminder_key)
        return True

    def append_session_event(self, event, payload=None):
        payload = self.redact_artifact(payload or {})
        envelope = RuntimeEvents.session_event(
            event,
            payload,
            session_id=self.session["id"],
            turn_id=self.current_turn_id,
            task_state=getattr(self, "current_task_state", None),
            created_at=now(),
        )
        self.session_event_path = self.session_store.append_event(self.session["id"], envelope)
        return envelope

    def append_session_event_for_record(self, item):
        role = item.get("role", "")
        if role == "user":
            self.append_session_event("user_message", {"content": item.get("content", ""), "history_event_id": item["event_id"]})
        elif role == "assistant":
            self.append_session_event("assistant_message", {"content": item.get("content", ""), "history_event_id": item["event_id"]})
        elif role == "tool":
            self.append_session_event(
                "tool_result",
                {
                    "name": item.get("name", ""),
                    "args": item.get("args", {}),
                    "content": clip(item.get("content", ""), 500),
                    "history_event_id": item["event_id"],
                },
            )

    def render_skills_text(self, user_message):
        if not self.feature_enabled("skills"):
            self.last_skill_metadata = {"selected": [], "selected_count": 0, "invoked": []}
            return "Available skills:\n- disabled"
        available = self.skill_catalog.discover()
        legacy_matches = self.skill_catalog.legacy_matches(user_message)
        invoked = list(getattr(self, "current_skill_invocations", []) or [])
        self.last_skill_metadata = self.skill_catalog.metadata(available, legacy_matches, invoked)
        return self.skill_catalog.render_prompt(available, invoked)

    def record_skill_invoked(self, metadata):
        metadata = dict(metadata or {})
        metadata_for_prompt = dict(metadata)
        if metadata.get("include_in_prompt", True):
            self.current_skill_invocations.append(metadata_for_prompt)
        event_payload = {
            "name": metadata.get("name", ""),
            "source": metadata.get("source", ""),
            "context": metadata.get("context", ""),
            "invocation_source": metadata.get("invocation_source", ""),
            "args": metadata.get("args", ""),
            "rendered_chars": int(metadata.get("rendered_chars", 0) or 0),
        }
        if self.current_turn_id:
            key = (
                self.current_turn_id,
                event_payload["name"],
                event_payload["source"],
                event_payload["invocation_source"],
                event_payload["args"],
            )
            if key in self._turn_skill_event_keys:
                return
            self._turn_skill_event_keys.add(key)
        self.append_session_event("skill_invoked", event_payload)

    def load_skill(self, name, args="", invocation_source="model"):
        if not self.feature_enabled("skills"):
            raise ValueError("skills are disabled")
        if self.allowed_tools is not None and not is_allowed(self.allowed_tools, "load_skill"):
            raise ValueError("tool 'load_skill' is not allowed in this session")
        return self.skill_runtime.invoke(name, args=args, invocation_source=invocation_source)

    @staticmethod
    def looks_sensitive_env_name(name):
        upper = str(name).upper()
        return any(upper == marker or upper.endswith(marker) or upper.endswith(f"_{marker}") for marker in SENSITIVE_ENV_NAME_MARKERS)

    def is_secret_env_name(self, name):
        upper = str(name).upper()
        return upper in self.secret_env_names or self.looks_sensitive_env_name(upper)

    def configured_secret_env_items(self):
        items = [
            (name, value)
            for name, value in os.environ.items()
            if str(name).upper() in self.secret_env_names and value
        ]
        items.sort(key=lambda item: item[0])
        return items

    def detected_secret_env_items(self):
        items = [
            (name, value)
            for name, value in os.environ.items()
            if self.is_secret_env_name(name) and value
        ]
        items.sort(key=lambda item: item[0])
        return items

    def secret_env_summary(self):
        names = [name for name, _ in self.configured_secret_env_items()]
        return {
            "secret_env_count": len(names),
            "secret_env_names": names,
        }

    def detected_secret_env_summary(self):
        names = [name for name, _ in self.detected_secret_env_items()]
        return {
            "secret_env_count": len(names),
            "secret_env_names": names,
        }

    def redact_text(self, text):
        text = str(text)
        for _, value in sorted(self.detected_secret_env_items(), key=lambda item: len(item[1]), reverse=True):
            text = text.replace(value, REDACTED_VALUE)
        return text

    def redact_artifact(self, value, key=None):
        if key and self.is_secret_env_name(key):
            return REDACTED_VALUE
        if isinstance(value, dict):
            return {
                str(item_key): self.redact_artifact(item_value, key=item_key)
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, str):
            redacted = self.redact_text(value)
            return redacted
        return value

    def shell_env(self):
        env = {
            name: os.environ[name]
            for name in self.shell_env_allowlist
            if name in os.environ
        }
        env["PWD"] = str(self.root)
        if "PATH" not in env and os.environ.get("PATH"):
            env["PATH"] = os.environ["PATH"]
        return env

    def prompt_metadata(self, user_message, prompt):
        _, metadata = self._build_prompt_and_metadata(user_message)
        return metadata

    def build_prompt_for_turn(self, user_message):
        return self._build_prompt_and_metadata(user_message)

    def _build_prompt_and_metadata(self, user_message):
        refresh = self.refresh_prefix()
        self.resume_state = self.evaluate_resume_state()
        prompt, metadata = self.context_manager.build(user_message)
        # 这里把“这轮 prompt 是怎么拼出来的”连同缓存相关状态一起记下来，
        # 后面 trace/report 才能解释清楚：为什么这一轮 prefix 变了、缓存有没有命中。
        metadata.update(
            {
                "prefix_chars": len(self.prefix),
                "workspace_chars": len(self.workspace.text()),
                "memory_chars": len(self.memory_text()),
                "history_chars": len(self.history_text()),
                "request_chars": len(user_message),
                "tool_count": len(self.tools),
                "workspace_docs": len(self.workspace.project_docs),
                "recent_commits": len(self.workspace.recent_commits),
                "prefix_hash": self.prefix_state.hash,
                "prompt_cache_key": self.prefix_state.hash,
                "workspace_fingerprint": self.prefix_state.workspace_fingerprint,
                "tool_signature": self.prefix_state.tool_signature,
                "skill_signature": self.prefix_state.skill_signature,
                "workspace_changed": refresh["workspace_changed"],
                "skills_changed": refresh.get("skills_changed", False),
                "prefix_changed": refresh["prefix_changed"],
                "prompt_cache_supported": bool(getattr(self.model_client, "supports_prompt_cache", False)),
                "resume_status": self.resume_state.get("status", CHECKPOINT_NONE_STATUS),
                "stale_summary_invalidations": int(self.resume_state.get("stale_summary_invalidations", 0)),
                "stale_paths": list(self.resume_state.get("stale_paths", [])),
                "runtime_identity_mismatch_fields": list(self.resume_state.get("runtime_identity_mismatch_fields", [])),
            }
        )
        metadata.update(self.detected_secret_env_summary())
        metadata["context_usage"] = build_context_usage(
            prompt=prompt,
            metadata=metadata,
            model=getattr(self.model_client, "model", ""),
            reserved_output_tokens=self.max_new_tokens,
        )
        return prompt, metadata

    def emit_trace(self, task_state, event, payload=None):
        payload = self.redact_artifact(payload or {})
        self._trace_sequence += 1
        payload = RuntimeEvents.trace_event(
            task_state,
            event,
            payload,
            sequence=self._trace_sequence,
            turn_id=self.current_turn_id,
            created_at=now(),
        )
        # trace 是运行中的逐事件时间线，适合回答“这一轮 agent 到底做了什么”。
        self.run_store.append_trace(task_state, payload)
        self.emit_runtime_event(event, payload)
        self._update_derived_runtime_state(task_state, event, payload)
        return payload

    def _update_derived_runtime_state(self, task_state, event, payload):
        if task_state is None:
            return []
        try:
            if event in {"task_list_updated", "tool_executed", "completion_assessed"}:
                task_state.tasks = completion.clone_tasks(self.current_tasks())
            if event in {"tool_executed", "completion_assessed", "verification_recorded"}:
                affected_paths = list((payload or {}).get("affected_paths", []) or [])
                changed_paths = list(task_state.changed_paths or [])
                for path in affected_paths:
                    if path not in changed_paths:
                        changed_paths.append(path)
                if changed_paths:
                    task_state.artifact_graph = build_artifact_graph(
                        self.root,
                        changed_paths,
                        task_state.verifications or [],
                    )
                    task_state.verification_plan = build_verification_plan(
                        self.root,
                        task_state.artifact_graph,
                        task_state.verifications or [],
                    )
            if event == "runtime_reminder_emitted":
                reminders = list(task_state.runtime_reminders or [])
                reminders.append(
                    {
                        "reason": str((payload or {}).get("reason", "")),
                        "message": str((payload or {}).get("message", "")),
                        "tool": str((payload or {}).get("tool", "")),
                        "created_at": str((payload or {}).get("created_at", "")),
                    }
                )
                task_state.runtime_reminders = reminders[-50:]
        except Exception as exc:  # noqa: BLE001 - derived state must not break the agent loop.
            errors = [
                {
                    "consumer": "derived_runtime_state",
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                    "event": event,
                }
            ]
            consumer_errors = list(getattr(task_state, "consumer_errors", []) or [])
            consumer_errors.extend(errors)
            task_state.consumer_errors = consumer_errors[-50:]
            return errors
        return []

    def emit_runtime_event(self, event, payload=None):
        callback = getattr(self, "event_callback", None)
        if callback is None:
            return None
        payload = self.redact_artifact(payload or {})
        envelope = RuntimeEvents.runtime_event(
            event,
            payload,
            session_id=self.session.get("id", ""),
            turn_id=self.current_turn_id,
            task_state=getattr(self, "current_task_state", None),
            created_at=now(),
        )
        try:
            callback(envelope)
        except Exception:
            return None
        return envelope

    def deliver_subagent_notification(self, notification):
        notification = dict(notification or {})
        status = str(notification.get("status", "completed"))
        event = {
            "completed": "subagent_completed",
            "failed": "subagent_failed",
            "killed": "subagent_killed",
        }.get(status, "subagent_notification_delivered")
        subagents = list(self.session.get("subagents", []) or [])
        task_id = str(notification.get("task_id", ""))
        replaced = False
        for index, item in enumerate(subagents):
            if str(item.get("task_id", "")) == task_id:
                subagents[index] = notification
                replaced = True
                break
        if not replaced:
            subagents.append(notification)
        self.session["subagents"] = subagents[-100:]
        task_state = getattr(self, "current_task_state", None)
        if task_state is not None:
            task_state.subagents = list(self.session["subagents"])
            self.emit_trace(task_state, event, {"subagent": notification})
        else:
            self.emit_runtime_event(event, {"subagent": notification})
        self.append_session_event(event, {"subagent": notification})
        rendered = self.render_subagent_notification(notification)
        if rendered:
            self.record({"role": "user", "content": rendered, "created_at": now(), "internal": True})
        self.session_path = self.session_store.save(self.session)
        return {"event": event, "subagent": notification}

    def record_subagent_started(self, payload):
        notification = dict(payload or {})
        if notification.get("status") == "started":
            notification["status"] = "running"
        notification.setdefault("status", "running")
        notification.setdefault("usage", {"tool_uses": 0, "duration_ms": 0})
        subagents = list(self.session.get("subagents", []) or [])
        task_id = str(notification.get("task_id", ""))
        replaced = False
        for index, item in enumerate(subagents):
            if str(item.get("task_id", "")) == task_id:
                subagents[index] = notification
                replaced = True
                break
        if not replaced:
            subagents.append(notification)
        self.session["subagents"] = subagents[-100:]
        task_state = getattr(self, "current_task_state", None)
        if task_state is not None:
            task_state.subagents = list(self.session["subagents"])
            self.emit_trace(task_state, "subagent_started", {"subagent": notification})
        else:
            self.emit_runtime_event("subagent_started", {"subagent": notification})
        self.append_session_event("subagent_started", {"subagent": notification})
        self.session_path = self.session_store.save(self.session)
        return {"event": "subagent_started", "subagent": notification}

    def drain_subagent_notifications(self):
        delivered = []
        for notification in self.subagent_manager.drain_notifications():
            delivered.append(self.deliver_subagent_notification(notification))
        return delivered

    @staticmethod
    def render_subagent_notification(notification):
        task_id = str(notification.get("task_id", ""))
        status = str(notification.get("status", ""))
        description = str(notification.get("description", ""))
        result = str(notification.get("result", "")).strip()
        error = str(notification.get("error", "")).strip()
        usage = dict(notification.get("usage", {}) or {})
        lines = [
            "<subagent-notification>",
            f"<task-id>{task_id}</task-id>",
            f"<status>{status}</status>",
            f"<description>{description}</description>",
        ]
        if result:
            lines.append(f"<result>{result}</result>")
        if error:
            lines.append(f"<error>{error}</error>")
        lines.extend(
            [
                "<usage>",
                f"  <tool_uses>{int(usage.get('tool_uses') or 0)}</tool_uses>",
                f"  <duration_ms>{int(usage.get('duration_ms') or 0)}</duration_ms>",
                "</usage>",
                "</subagent-notification>",
            ]
        )
        return "\n".join(lines)

    def capture_workspace_snapshot(self):
        snapshot = {}
        for path in self.root.rglob("*"):
            try:
                relative_parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part in IGNORED_PATH_NAMES for part in relative_parts):
                continue
            if not path.is_file():
                continue
            try:
                snapshot[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                continue
        return snapshot

    @staticmethod
    def diff_workspace_snapshots(before, after):
        changed_paths = []
        summaries = []
        all_paths = sorted(set(before) | set(after))
        for path in all_paths:
            if before.get(path) == after.get(path):
                continue
            changed_paths.append(path)
            if path not in before:
                summaries.append(f"created:{path}")
            elif path not in after:
                summaries.append(f"deleted:{path}")
            else:
                summaries.append(f"modified:{path}")
        return changed_paths, summaries

    def create_checkpoint(self, task_state, user_message, trigger):
        state = self.checkpoint_state()
        current = self.current_checkpoint()
        checkpoint_id = "ckpt_" + uuid.uuid4().hex[:8]
        key_files = []
        freshness = {}
        for path in self.memory.to_dict()["working"]["recent_files"]:
            file_freshness = memorylib.file_freshness(path, self.root)
            freshness[path] = file_freshness
            key_files.append({"path": path, "freshness": file_freshness})
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": current.get("checkpoint_id", "") if current else "",
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "created_at": now(),
            "current_goal": str(user_message),
            "completed": [task_state.final_answer] if task_state.final_answer else [],
            "excluded": [],
            "current_blocker": "" if str(task_state.stop_reason or "") in ("", "final_answer_returned") else str(task_state.stop_reason),
            "next_step": self.infer_next_step(task_state),
            "key_files": key_files,
            "freshness": freshness,
            "summary": f"{trigger}: {clip(str(user_message), 120)}",
            "runtime_identity": self.current_runtime_identity(),
        }
        state["items"][checkpoint_id] = checkpoint
        state["current_id"] = checkpoint_id
        task_state.checkpoint_id = checkpoint_id
        self.session["runtime_identity"] = checkpoint["runtime_identity"]
        self.session_path = self.session_store.save(self.session)
        return checkpoint

    def infer_next_step(self, task_state):
        if task_state.status == "completed":
            return "No next step recorded."
        if task_state.stop_reason == "step_limit_reached":
            return "Resume from the latest checkpoint and continue the task."
        if task_state.last_tool:
            return f"Decide the next action after {task_state.last_tool}."
        return "Continue the task from the latest checkpoint."

    def update_memory_after_tool(self, name, args, result):
        """把少量高价值工具结果沉淀到 working memory。

        为什么存在：
        并不是每个工具结果都值得长期带进下一轮 prompt。完整结果已经进了
        `history`，这里只挑少量“下一轮大概率还会用到”的事实做提纯，
        例如最近读写过哪些文件、某个文件读出来的短摘要。

        输入 / 输出：
        - 输入：工具名 `name`、参数 `args`、执行结果 `result`
        - 输出：无显式返回值，副作用是更新 `self.memory`

        在 agent 链路里的位置：
        它发生在 `run_tool()` 真正执行完工具之后、下一轮 prompt 组装之前。
        也就是说：工具结果先进入完整历史，再由这个函数择优沉淀成轻量记忆。
        """
        if not self.feature_enabled("memory"):
            return
        if name == "write_files":
            for item in args.get("files", []) or []:
                path = item.get("path")
                if path:
                    canonical_path = self.memory.canonical_path(path)
                    self.memory.remember_file(canonical_path)
                    self.memory.invalidate_file_summary(canonical_path)
            return

        path = args.get("path")
        if not path:
            return
        canonical_path = self.memory.canonical_path(path)
        # 不是所有工具结果都进入工作记忆。
        # 读文件会生成摘要；写文件/patch 会让旧摘要失效，因为它们可能过期了。
        if name in {"read_file", "write_file", "patch_file"}:
            self.memory.remember_file(canonical_path)
        if name == "read_file":
            summary = memorylib.summarize_read_result(result)
            self.memory.set_file_summary(canonical_path, summary)
            self.memory.append_note(summary, tags=(canonical_path,), source=canonical_path)
        elif name in {"write_file", "patch_file"}:
            self.memory.invalidate_file_summary(canonical_path)

    def note_tool(self, name, args, result):
        self.update_memory_after_tool(name, args, result)

    def tool_policy_state(self):
        return self.tool_policy_controller.tool_policy_state(self)

    def read_ledger(self):
        return self.tool_policy_controller.read_ledger(self)

    def canonical_tool_path(self, args):
        return self.tool_policy_controller.canonical_tool_path(self, args)

    def validate_prior_read_policy(self, name, args):
        return self.tool_policy_controller.validate_prior_read_policy(self, name, args)

    def validate_existing_write_read_policy(self, name, args):
        return self.tool_policy_controller.validate_existing_write_read_policy(self, name, args)

    def validate_write_scope_policy(self, name, args):
        return self.tool_policy_controller.validate_write_scope_policy(self, name, args)

    def is_active_plan_file_write(self, name, args):
        return self.tool_policy_controller.is_active_plan_file_write(self, name, args)

    def validate_runtime_mode_policy(self, name, args):
        return self.tool_policy_controller.validate_runtime_mode_policy(self, name, args)

    def update_tool_policy_after_tool(self, name, args, result, status):
        return self.tool_policy_controller.update_tool_policy_after_tool(self, name, args, result, status)

    def materialize_tool_result(self, name, args, raw_result, max_chars):
        del args
        raw_result = str(raw_result)
        max_chars = int(max_chars or 4000)
        metadata = {
            "artifact_relpath": "",
            "artifact_chars": 0,
            "result_raw_chars": len(raw_result),
            "result_rendered_chars": min(len(raw_result), max_chars),
        }
        if len(raw_result) <= max_chars:
            return raw_result, metadata
        self._tool_artifact_sequence += 1
        task_state = self.current_task_state
        if task_state is None:
            task_state = TaskState.create(run_id="run_tool_direct", task_id="task_tool_direct", user_request="direct tool call")
        artifact_path = self.run_store.write_tool_artifact(task_state, self._tool_artifact_sequence, name, raw_result)
        artifact_relpath = artifact_path.relative_to(self.root).as_posix()
        rendered = clip(raw_result, max_chars)
        rendered += f"\n[full_result_artifact: {artifact_relpath}]"
        metadata.update(
            {
                "artifact_relpath": artifact_relpath,
                "artifact_chars": len(raw_result),
                "result_rendered_chars": len(rendered),
            }
        )
        return rendered, metadata

    def record_process_note_for_tool(self, name, metadata):
        status = str(metadata.get("tool_status", "")).strip()
        if status not in {"partial_success", "error", "rejected"}:
            return
        affected_paths = [str(path).strip() for path in metadata.get("affected_paths", []) if str(path).strip()]
        path_text = ", ".join(affected_paths) or "workspace"
        if status == "partial_success":
            text = f"{name} partial_success on {path_text}; inspect diff before retry"
        elif status == "error":
            text = f"{name} error on {path_text}; check the failure before retry"
        else:
            text = f"{name} rejected; choose a different action before retry"
        tags = ["process", status, *affected_paths]
        self.memory.append_note(text, tags=tuple(tags), source=name, kind="process")
        self.session["memory"] = self.memory.to_dict()

    def reject_durable_reason(self, note_text):
        text = str(note_text or "").strip()
        lowered = text.lower()
        if not text:
            return "empty"
        if REDACTED_VALUE in text or SECRET_SHAPED_TEXT_PATTERN.search(text):
            return "secret_shaped"
        checkpoint_like_prefixes = (
            "current goal",
            "current blocker",
            "next step",
            "current phase",
            "key files",
            "freshness",
            "当前目标",
            "当前卡点",
            "下一步",
            "当前阶段",
            "关键文件",
            "已完成",
            "已排除",
        )
        if any(lowered.startswith(prefix) for prefix in checkpoint_like_prefixes):
            return "transient_task_state"
        if re.search(r"(?i)\b(stdout|stderr|traceback|exit_code)\b", text) or len(text) > 220:
            return "noisy_output"
        return ""

    def extract_durable_promotions(self, user_message, final_answer):
        user_text = str(user_message or "")
        if not (DURABLE_MEMORY_INTENT_PATTERN.search(user_text) or DURABLE_MEMORY_INTENT_ZH_PATTERN.search(user_text)):
            return [], []
        promotions = []
        rejections = []
        for line in str(final_answer or "").splitlines():
            text = line.strip()
            if not text or REDACTED_VALUE in text:
                continue
            for topic, pattern in DURABLE_MEMORY_LINE_PATTERNS:
                match = pattern.match(text)
                if not match:
                    continue
                note_text = match.group(1).strip()
                if note_text:
                    reason = self.reject_durable_reason(note_text)
                    if reason:
                        rejections.append(f"{topic}:{reason}")
                        break
                    promotions.append((topic, note_text))
                break
        return promotions, rejections

    def promote_durable_memory(self, user_message, final_answer):
        promotions, rejections = self.extract_durable_promotions(user_message, final_answer)
        promoted, superseded = self.memory.promote_durable(promotions)
        self.session["memory"] = self.memory.to_dict()
        self.last_durable_promotions = promoted
        self.last_durable_rejections = rejections
        self.last_durable_superseded = superseded
        return promoted, rejections, superseded

    def _execute_tool_step(
        self,
        task_state,
        run_context,
        user_message,
        name,
        args,
        *,
        forced_result=None,
        source="",
        checkpoint_trigger="tool_executed",
    ):
        return self.run_lifecycle.execute_tool_step(
            self,
            task_state,
            run_context,
            user_message,
            name,
            args,
            forced_result=forced_result,
            source=source,
            checkpoint_trigger=checkpoint_trigger,
        )

    def execute_tool_request(
        self,
        task_state,
        run_context,
        user_message,
        name,
        args,
        *,
        forced_result=None,
        source="",
        checkpoint_trigger="tool_executed",
    ):
        return self._execute_tool_step(
            task_state,
            run_context,
            user_message,
            name,
            args,
            forced_result=forced_result,
            source=source,
            checkpoint_trigger=checkpoint_trigger,
        )

    def _finish_run(
        self,
        task_state,
        user_message,
        final,
        run_started_at,
        *,
        checkpoint_trigger=None,
        promote_memory=False,
        assess_completion=False,
    ):
        return self.run_lifecycle.finish_run(
            self,
            task_state,
            user_message,
            final,
            run_started_at,
            checkpoint_trigger=checkpoint_trigger,
            promote_memory=promote_memory,
            assess_completion=assess_completion,
        )

    def finish_run(
        self,
        task_state,
        user_message,
        final,
        run_started_at,
        *,
        checkpoint_trigger=None,
        promote_memory=False,
        assess_completion=False,
    ):
        return self._finish_run(
            task_state,
            user_message,
            final,
            run_started_at,
            checkpoint_trigger=checkpoint_trigger,
            promote_memory=promote_memory,
            assess_completion=assess_completion,
        )

    def ask(self, user_message, cancel_event=None):
        """Prepare a turn and delegate the runtime loop to RuntimeEngine."""
        run_started_at = time.monotonic()
        raw_user_message = str(user_message)
        skill_command = parse_skill_command(raw_user_message)
        prompt_user_message = skill_command.args if skill_command is not None else raw_user_message
        self.memory.set_task_summary(prompt_user_message)
        task_state = TaskState.create(run_id=self.new_run_id(), task_id=self.new_task_id(), user_request=prompt_user_message)
        task_state.resume_status = self.resume_state.get("status", CHECKPOINT_NONE_STATUS)
        task_state.stage = "planning" if completion.is_complex_request(prompt_user_message) else "implementing"
        task_state.tasks = self.current_tasks()
        task_state.verifications = []
        task_state.changed_paths = []
        task_state.completion_gate = {"blocked": False, "status": "running", "warnings": [], "reasons": []}
        task_state.verification_plan = {}
        task_state.control_decisions = []
        task_state.subagents = list(self.session.get("subagents", []) or [])
        self.current_task_state = task_state
        self.current_turn_id = "turn_" + uuid.uuid4().hex[:10]
        self._turn_skill_event_keys = set()
        self.current_skill_invocations = []
        self._runtime_reminder_keys = set()
        self._trace_sequence = 0
        self.current_run_dir = self.run_store.start_run(task_state)
        self.emit_trace(
            task_state,
            "run_started",
            {
                "task_id": task_state.task_id,
                "user_request": clip(prompt_user_message, 300),
            },
        )
        if skill_command is not None:
            try:
                loaded_skill = self.load_skill(skill_command.name, skill_command.args, invocation_source="user")
            except Exception as exc:
                final = f"error: {exc}"
                self.record({"role": "user", "content": raw_user_message, "created_at": now()})
                task_state.stop("skill_invocation_failed", status="failed", final_answer=final)
                return self._finish_run(
                    task_state,
                    prompt_user_message,
                    final,
                    run_started_at,
                    checkpoint_trigger="skill_invocation_failed",
                    promote_memory=False,
                )
            if not self.current_skill_invocations:
                self.record({"role": "user", "content": raw_user_message, "created_at": now()})
                task_state.finish_success(loaded_skill)
                return self._finish_run(
                    task_state,
                    prompt_user_message,
                    loaded_skill,
                    run_started_at,
                    checkpoint_trigger="skill_invoked",
                    promote_memory=True,
                )

        max_steps = self.effective_max_steps(prompt_user_message)
        run_context = RunContext.create(
            task_state=task_state,
            user_message=prompt_user_message,
            max_steps=max_steps,
            max_new_tokens=self.max_new_tokens,
        )
        # RuntimeEngine owns the model/tool/final loop; Pico only prepares the turn.
        result = self.runtime_engine.run(
            self,
            task_state,
            run_context,
            RunRequest(
                user_message=prompt_user_message,
                raw_user_message=raw_user_message,
                run_started_at=run_started_at,
                cancel_event=cancel_event,
            ),
        )
        return result.final_answer

    def run_tool(self, name, args):
        """Execute one guarded tool call."""
        execution = ToolRunner(self.tool_execution_context()).run(name, args)
        self._last_tool_result_metadata = dict(execution.metadata)
        if execution.metadata.get("tool_status") == "ok":
            self.update_memory_after_tool(name, args, execution.content)
            self.update_tool_policy_after_tool(name, args, execution.content, execution.metadata.get("tool_status", ""))
        if execution.metadata.get("tool_status") != "rejected":
            self.record_process_note_for_tool(name, execution.metadata)
        return execution.content

    def tool_execution_context(self):
        return ToolExecutionContext(
            tools=self.tools,
            allowed_tools=self.allowed_tools,
            workspace=self.workspace,
            read_only=self.read_only,
            read_only_stall_limit=self.read_only_stall_limit,
            preflight_tool=self.preflight_tool,
            is_active_plan_file_write=self.is_active_plan_file_write,
            validate_tool=self.validate_tool,
            tool_example=self.tool_example,
            tool_rejection_recovery_message=self.tool_rejection_recovery_message,
            capture_workspace_snapshot=self.capture_workspace_snapshot,
            materialize_tool_result=self.materialize_tool_result,
            diff_workspace_snapshots=self.diff_workspace_snapshots,
            tool_activity_description=self.tool_activity_description,
        )

    def repeated_tool_call(self, name, args):
        # agent 很常见的一种坏循环，是在没有新信息的情况下反复发起同一调用。
        # 这里提前挡掉最简单的这种循环。
        tool_events = [item for item in self.session["history"] if item["role"] == "tool"]
        if len(tool_events) < 2:
            return False
        recent = tool_events[-2:]
        return all(item["name"] == name and item["args"] == args for item in recent)

    def changed_path_read_stall(self, name, args):
        if name != "read_file" or self.current_task_state is None:
            return ""
        if completion.latest_verification_status(self.current_task_state.verifications or []) == "failed":
            return ""
        path = str((args or {}).get("path") or "")
        if not path or path not in set(self.current_task_state.changed_paths or []):
            return ""
        if self.consecutive_read_only_tool_count() < 2:
            return ""
        return (
            "error: you are rereading a file changed in this run without a failed verification. "
            "Mark the related todo complete, write the next files, run verification, or patch a specific issue."
        )

    def consecutive_read_only_tool_count(self):
        count = 0
        for item in reversed(self.session["history"]):
            if item.get("role") != "tool":
                continue
            tool = self.tools.get(item.get("name", ""))
            if tool and tool.get("read_only", not tool["risky"]):
                count += 1
                continue
            break
        return count

    @staticmethod
    def new_task_id():
        return "task_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    @staticmethod
    def new_run_id():
        return "run_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    def build_report(self, task_state):
        # report 是一次运行的最终摘要；
        # 和 trace 的区别在于，trace 关注过程，report 关注结果与关键指标。
        completion_assessment = dict(task_state.completion_gate or {})
        final_status = str(completion_assessment.get("status") or task_state.status)
        return {
            "run_id": task_state.run_id,
            "task_id": task_state.task_id,
            "status": task_state.status,
            "final_status": final_status,
            "stop_reason": task_state.stop_reason,
            "final_answer": task_state.final_answer,
            "tool_steps": task_state.tool_steps,
            "attempts": task_state.attempts,
            "checkpoint_id": task_state.checkpoint_id,
            "resume_status": task_state.resume_status,
            "task_state": task_state.to_dict(),
            "tasks": list(task_state.tasks or []),
            "verifications": list(task_state.verifications or []),
            "changed_paths": list(task_state.changed_paths or []),
            "artifact_graph": dict(task_state.artifact_graph or {}),
            "verification_plan": dict(task_state.verification_plan or {}),
            "control_decisions": list(task_state.control_decisions or []),
            "runtime_reminders": list(task_state.runtime_reminders or []),
            "subagents": list(task_state.subagents or self.session.get("subagents", []) or []),
            "completion_assessment": completion_assessment,
            "completion_gate": completion_assessment,
            "prompt_metadata": self.last_prompt_metadata,
            "session_events_path": str(self.session_store.event_path(self.session["id"])),
            "trace_path": str(self.run_store.trace_path(task_state)),
            "durable_promotions": list(self.last_durable_promotions),
            "durable_rejections": list(self.last_durable_rejections),
            "durable_superseded": list(self.last_durable_superseded),
            "redacted_env": self.detected_secret_env_summary(),
        }

    def tool_example(self, name):
        return toolkit.tool_example(name)

    def tool_rejection_recovery_message(self, name, args, tool_error_code, error_text=""):
        if tool_error_code not in {"prior_read_required", "stale_prior_read"}:
            return ""
        path = str((args or {}).get("path", "")).strip()
        if not path:
            match = re.search(r"read_file for (?P<path>\S+)", str(error_text or ""))
            path = match.group("path") if match else ""
        if not path:
            return ""
        return (
            f'Runtime recovery: {name} was rejected by the file-safety policy. '
            f'Next tool: read_file with path "{path}", then retry with patch_file or write_file after reading the current contents.'
        )

    def should_enforce_runtime_reminder(self, reminder, name, args):
        reason = str((reminder or {}).get("reason", ""))
        if reason not in {"task_status_stale", "implementation_needs_file_evidence"}:
            return False
        tool = self.tools.get(name) or {}
        if tool.get("read_only", not tool.get("risky", True)):
            return True
        if name == "run_shell" and not completion.is_verification_command(str((args or {}).get("command", ""))):
            return True
        return False

    def runtime_reminder_rejection(self, reminder, name, args):
        message = str((reminder or {}).get("message", "Runtime reminder ignored.")).strip()
        self._last_tool_result_metadata = {
            "tool_status": "rejected",
            "tool_error_code": "progress_guard_stale_task",
            "security_event_type": "",
            "risk_level": "low",
            "read_only": True,
            "affected_paths": [],
            "workspace_changed": False,
            "diff_summary": [],
        }
        return (
            "error: runtime progress guard blocked this inspection because the previous reminder was ignored. "
            f"{message} Next tool must make progress: todo_update the active task, write/patch the next artifact, "
            "or run a real verification command."
        )

    def tool_activity_description(self, name, args=None):
        return toolkit.tool_activity_description(name, args or {})

    def validate_tool(self, name, args):
        """把通用工具校验和 runtime 级额外约束串起来。"""
        toolkit.validate_tool(self, name, args)
        self.validate_runtime_mode_policy(name, args)
        self.validate_write_scope_policy(name, args)
        if not self.is_active_plan_file_write(name, args):
            self.validate_prior_read_policy(name, args)
            self.validate_existing_write_read_policy(name, args)
        if name == "delegate":
            if self.depth >= self.max_depth:
                raise ValueError("delegate depth exceeded")

    def preflight_tool(self, name, args, tool):
        return self.policy_engine.before_tool(
            self,
            ToolRequest(name=name, args=dict(args or {}), tool=dict(tool or {})),
        ).to_preflight()

    def tool_list_files(self, args):
        return toolkit.tool_list_files(self, args)

    def tool_read_file(self, args):
        return toolkit.tool_read_file(self, args)

    def tool_glob(self, args):
        return toolkit.tool_glob(self, args)

    def tool_grep(self, args):
        return toolkit.tool_grep(self, args)

    def tool_search(self, args):
        return toolkit.tool_search(self, args)

    def tool_ask_user(self, args):
        return toolkit.tool_ask_user(self, args)

    def tool_run_shell(self, args):
        return toolkit.tool_run_shell(self, args)

    def tool_write_file(self, args):
        return toolkit.tool_write_file(self, args)

    def tool_patch_file(self, args):
        return toolkit.tool_patch_file(self, args)

    def tool_delegate(self, args):
        return toolkit.tool_delegate(self, args)

    def approve(self, name, args):
        if self.read_only:
            if name == "run_shell":
                return is_read_only_shell_command(str((args or {}).get("command", "")))
            return False
        if self.approval_policy == "auto":
            return True
        if self.approval_policy == "never":
            return False
        callback = getattr(self, "approval_callback", None)
        if callback is not None:
            metadata = {
                "risk_level": "high",
                "read_only": False,
                "approval_policy": self.approval_policy,
            }
            return bool(callback(name, args, metadata))
        try:
            answer = input(f"approve {name} {json.dumps(args, ensure_ascii=True)}? [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}

    @staticmethod
    def parse(raw):
        """把模型原始输出解析成 runtime 可执行的动作或最终答案。

        为什么存在：
        模型输出首先是自然语言文本，而 runtime 需要的是结构化决策：
        “这是工具调用”还是“这是最终答案”。如果没有这层解析，后面的工具校验、
        审批和执行链路就没法可靠工作。

        输入 / 输出：
        - 输入：模型返回的原始文本 `raw`
        - 输出：`(kind, payload)`，其中 `kind` 可能是 `tool`、`final`、`retry`

        在 agent 链路里的位置：
        它位于 `model_client.complete()` 之后、`run_tool()` 之前，是模型输出
        进入平台控制流的第一道结构化关口。
        """
        return parse_model_output(raw)

    @staticmethod
    def retry_notice(problem=None):
        return model_retry_notice(problem)

    @staticmethod
    def parse_xml_tool(raw):
        return parse_xml_model_tool(raw)

    @staticmethod
    def parse_attrs(text):
        return parse_decision_attrs(text)

    @staticmethod
    def extract(text, tag):
        return extract_decision_tag(text, tag)

    @staticmethod
    def extract_raw(text, tag):
        return extract_raw_decision_tag(text, tag)

    def reset(self):
        self.session["history"] = []
        self.session["tasks"] = []
        self.session["verifications"] = []
        self.session["subagents"] = []
        self.session["memory"].clear()
        self.session["memory"].update(memorylib.default_memory_state())
        self.memory = memorylib.LayeredMemory(self.session["memory"], workspace_root=self.root)
        self.session_store.save(self.session)

    def path(self, raw_path):
        path = Path(raw_path)
        path = path if path.is_absolute() else self.root / path
        resolved = path.resolve()
        # 所有文件类工具都被锚定在 workspace root 之下。
        # 这样既能防住 "../" 逃逸，也能防住符号链接解析后跳出仓库。
        if os.path.commonpath([str(self.root), str(resolved)]) != str(self.root):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return resolved


MiniAgent = Pico

__all__ = ["MiniAgent", "Pico", "SessionStore"]
