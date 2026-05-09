"""命令行入口。

这个模块负责把“用户怎么启动 pico”翻译成 runtime 能理解的对象：
解析参数、挑模型后端、构建工作区快照、恢复或新建 session，
最后进入 one-shot、TUI 或普通 REPL。
"""

import argparse
import os
import shutil
import sys
import textwrap

from .config import load_env_file, load_project_env, provider_env
from .core.agent import Pico
from .core.session import SessionStore
from .core.workspace import WorkspaceContext, middle
from .features.verifier_driver import select_verification_action
from .providers.clients import (
    AnthropicCompatibleModelClient,
    AnthropicSDKModelClient,
    OllamaModelClient,
    OpenAICompatibleModelClient,
    OpenAISDKModelClient,
)

DEFAULT_SECRET_ENV_NAMES = (
    "PICO_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_TOKEN",
    "PICO_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "PICO_DEEPSEEK_API_KEY",
    "DEEPSEEK_API_KEY",
    "PICO_RIGHT_CODES_API_KEY",
    "RIGHT_CODES_API_KEY",
    "GITHUB_PAT",
    "GH_PAT",
)

WELCOME_ART = (
    "        /\\___/\\\\",
    "       (  o o  )",
    "       /   ^   \\\\",
    "      /|       |\\\\",
)
WELCOME_NAME = "pico"
WELCOME_SUBTITLE = "local coding agent"
WELCOME_STATUS = "calm shell, ready for work"
HELP_DETAILS = textwrap.dedent(
    """\
    Commands:
    /help    Show this help message.
    /memory  Show the agent's distilled working memory.
    /session Show the path to the saved session file.
    /tasks   Show the current task ledger.
    /verify  Show recent verification artifacts.
    /skills  List available Pico skills.
    /skill   Load and run a Pico skill: /skill <name> [args] or /skill:<name> [args].
    /history List saved sessions for this workspace.
    /resume  Resume a saved session by id or prefix.
    /compact Compact older history into a persisted summary.
    /plan    Enter read-only plan mode with a plan artifact.
    /execute Exit plan mode and return to normal execution.
    /reset   Clear the current session history and memory.
    /exit    Exit the agent.
    """
).strip()


DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_OPENAI_BASE_URL = "https://www.right.codes/codex/v1"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_ANTHROPIC_BASE_URL = "https://www.right.codes/claude/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
LEGACY_SECRET_ENV_NAMES_VAR = "MINI_CODING_AGENT_SECRET_ENV_NAMES"
SECRET_ENV_NAMES_VAR = "PICO_SECRET_ENV_NAMES"


def _normalize_provider_args(args):
    if getattr(args, "deepseek", False):
        args.provider = "deepseek"
    if not getattr(args, "provider", None):
        args.provider = "openai"
    if getattr(args, "provider", "openai") == "openai" and str(getattr(args, "model", "") or "").lower() == "deepseek":
        args.provider = "deepseek"
        args.model = None
    return args


def _effective_model(args, provider):
    # 模型选择优先级：
    # 1. 用户显式传入 --model
    # 2. provider 对应的环境变量
    # 3. 代码里的默认值
    explicit_model = getattr(args, "model", None)
    if explicit_model:
        return explicit_model
    if provider in {"openai", "openai-compatible"}:
        model = provider_env("PICO_OPENAI_MODEL", ("OPENAI_MODEL",))
        if model:
            return model
        return DEFAULT_OPENAI_MODEL
    if provider in {"anthropic", "anthropic-sdk", "anthropic-compatible"}:
        model = provider_env("PICO_ANTHROPIC_MODEL", ("ANTHROPIC_MODEL",))
        if model:
            return model
        return DEFAULT_ANTHROPIC_MODEL
    if provider == "deepseek":
        model = provider_env("PICO_DEEPSEEK_MODEL", ("DEEPSEEK_MODEL",))
        if model:
            return model
        return DEFAULT_DEEPSEEK_MODEL
    return DEFAULT_OLLAMA_MODEL


def _configured_secret_names(args):
    configured_secret_names = set(DEFAULT_SECRET_ENV_NAMES)
    configured_secret_names.update(str(name).upper() for name in args.secret_env_names)
    extra_names = os.environ.get(SECRET_ENV_NAMES_VAR, "")
    if not extra_names.strip():
        extra_names = os.environ.get(LEGACY_SECRET_ENV_NAMES_VAR, "")
    if extra_names.strip():
        configured_secret_names.update(
            item.strip().upper()
            for item in extra_names.split(",")
            if item.strip()
        )
    return sorted(configured_secret_names)


def _build_model_client(args):
    provider = getattr(args, "provider", "openai")
    # CLI 只负责把 provider 选择翻译成具体 client。
    # 真正的提示词格式、缓存支持、HTTP 协议差异，都封装在 models.py 里。
    if provider == "openai":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("PICO_OPENAI_API_BASE", ("OPENAI_API_BASE",), DEFAULT_OPENAI_BASE_URL)
        api_key = provider_env("PICO_OPENAI_API_KEY", ("OPENAI_API_KEY",))
        return OpenAISDKModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
            api_mode=getattr(args, "openai_api_mode", "auto"),
        )
    if provider == "openai-compatible":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("PICO_OPENAI_API_BASE", ("OPENAI_API_BASE",), DEFAULT_OPENAI_BASE_URL)
        api_key = provider_env("PICO_OPENAI_API_KEY", ("OPENAI_API_KEY",))
        return OpenAICompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
            api_mode=getattr(args, "openai_api_mode", "auto"),
        )
    if provider in {"anthropic", "anthropic-sdk"}:
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("PICO_ANTHROPIC_API_BASE", ("ANTHROPIC_API_BASE",), DEFAULT_ANTHROPIC_BASE_URL)
        api_key = provider_env(
            "PICO_ANTHROPIC_API_KEY",
            ("ANTHROPIC_API_KEY", "PICO_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY", "PICO_OPENAI_API_KEY", "OPENAI_API_KEY"),
        )
        return AnthropicSDKModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )
    if provider == "anthropic-compatible":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("PICO_ANTHROPIC_API_BASE", ("ANTHROPIC_API_BASE",), DEFAULT_ANTHROPIC_BASE_URL)
        api_key = provider_env(
            "PICO_ANTHROPIC_API_KEY",
            ("ANTHROPIC_API_KEY", "PICO_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY", "PICO_OPENAI_API_KEY", "OPENAI_API_KEY"),
        )
        return AnthropicCompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )
    if provider == "deepseek":
        model = _effective_model(args, provider)
        base_url = getattr(args, "base_url", None) or provider_env("PICO_DEEPSEEK_API_BASE", ("DEEPSEEK_API_BASE",), DEFAULT_DEEPSEEK_BASE_URL)
        api_key = provider_env("PICO_DEEPSEEK_API_KEY", ("DEEPSEEK_API_KEY",))
        return AnthropicCompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=args.temperature,
            timeout=getattr(args, "openai_timeout", getattr(args, "ollama_timeout", 300)),
        )

    model = _effective_model(args, provider)
    host = getattr(args, "host", DEFAULT_OLLAMA_HOST)
    return OllamaModelClient(
        model=model,
        host=host,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.ollama_timeout,
    )


def build_welcome(agent, model, host):
    width = max(68, min(shutil.get_terminal_size((80, 20)).columns, 84))
    inner = width - 4
    gap = 3
    left_width = (inner - gap) // 2
    right_width = inner - gap - left_width

    def row(text):
        body = middle(text, width - 4)
        return f"| {body.ljust(width - 4)} |"

    def divider(char="-"):
        return "+" + char * (width - 2) + "+"

    def center(text):
        body = middle(text, inner)
        return f"| {body.center(inner)} |"

    def cell(label, value, size):
        body = middle(f"{label:<9} {value}", size)
        return body.ljust(size)

    def pair(left_label, left_value, right_label, right_value):
        left = cell(left_label, left_value, left_width)
        right = cell(right_label, right_value, right_width)
        return f"| {left}{' ' * gap}{right} |"

    line = divider("=")
    rows = [center(text) for text in WELCOME_ART]
    rows.extend(
        [
            center(WELCOME_NAME),
            center(WELCOME_SUBTITLE),
            center(WELCOME_STATUS),
            divider("-"),
            row(""),
            row("WORKSPACE  " + middle(agent.workspace.cwd, inner - 11)),
            pair("MODEL", model, "BRANCH", agent.workspace.branch),
            pair("APPROVAL", agent.approval_policy, "SESSION", agent.session["id"]),
            row(""),
        ]
    )
    return "\n".join([line, *rows, line])


def build_agent(args):
    """根据 CLI 参数装配出一个可运行的 Pico 实例。

    为什么存在：
    命令行参数只是字符串和开关，runtime 需要的是已经装配好的对象图：
    model client、workspace snapshot、session store、secret 配置等。
    这个函数负责把“启动参数”翻译成“agent 运行现场”。

    输入 / 输出：
    - 输入：`argparse` 解析后的 `args`
    - 输出：一个新的 `Pico`，或一个从旧 session 恢复出来的 `Pico`

    在 agent 链路里的位置：
    它是整个程序启动链路里最靠近 runtime 的装配点。`main()` 先调它，
    得到 agent 后，后面无论是 one-shot 还是 REPL 模式，都会落到 `ask()`。
    """
    # 这里是 CLI 到 runtime 的装配点：
    args = _normalize_provider_args(args)
    # 先采集工作区快照和加载项目级环境，再整理 secret 名单、模型后端和 session。
    workspace = WorkspaceContext.build(args.cwd)
    load_project_env(workspace.repo_root)
    if getattr(args, "env_file", None):
        load_env_file(args.env_file)
    configured_secret_names = _configured_secret_names(args)
    store = SessionStore(workspace.repo_root + "/.pico/sessions")
    model = _build_model_client(args)
    session_id = args.resume
    allowed_tools = getattr(args, "allowed_tools", None) or None
    if session_id == "latest":
        session_id = store.latest()
    if session_id:
        return Pico.from_session(
            model_client=model,
            workspace=workspace,
            session_store=store,
            session_id=session_id,
            approval_policy=args.approval,
            max_steps=args.max_steps,
            max_new_tokens=args.max_new_tokens,
            secret_env_names=configured_secret_names,
            allowed_tools=allowed_tools,
        )
    return Pico(
        model_client=model,
        workspace=workspace,
        session_store=store,
        approval_policy=args.approval,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        secret_env_names=configured_secret_names,
        allowed_tools=allowed_tools,
    )


def build_arg_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Minimal coding agent for Ollama, OpenAI-compatible, Anthropic-compatible, or DeepSeek models.",
    )
    parser.add_argument("prompt", nargs="*", help="Optional one-shot prompt.")
    parser.add_argument("--tui", action="store_true", help="Start the Textual terminal UI. This is the default when no prompt is given.")
    parser.add_argument("--repl", action="store_true", help="Start the legacy plain REPL instead of the default TUI.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument("--env-file", default=None, help="Load provider configuration from an explicit .env file before building the model client.")
    parser.add_argument("--deepseek", action="store_true", help="Shortcut for --provider deepseek.")
    parser.add_argument(
        "--provider",
        choices=("ollama", "openai", "openai-compatible", "anthropic", "anthropic-sdk", "anthropic-compatible", "deepseek"),
        default="openai",
        help="Model backend to use.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override. Defaults to qwen3.5:4b for Ollama, PICO_OPENAI_MODEL for openai, PICO_ANTHROPIC_MODEL for anthropic, and PICO_DEEPSEEK_MODEL for deepseek when set.",
    )
    parser.add_argument("--host", default=DEFAULT_OLLAMA_HOST, help="Ollama server URL.")
    parser.add_argument("--base-url", default=None, help="Provider API base URL for openai, anthropic, or deepseek.")
    parser.add_argument("--ollama-timeout", type=int, default=300, help="Ollama request timeout in seconds.")
    parser.add_argument("--openai-timeout", type=int, default=300, help="OpenAI-compatible request timeout in seconds.")
    parser.add_argument("--openai-api-mode", choices=("auto", "responses", "chat"), default="auto", help="OpenAI-compatible API shape. Auto uses chat completions for known chat-only gateways.")
    parser.add_argument("--resume", default=None, help="Session id to resume or 'latest'.")
    parser.add_argument("--approval", choices=("ask", "auto", "never"), default="ask", help="Approval policy for risky tools.")
    parser.add_argument(
        "--secret-env-name",
        dest="secret_env_names",
        action="append",
        default=[],
        help="Extra environment variable names to treat as secrets for trace/report redaction.",
    )
    parser.add_argument("--max-steps", type=int, default=6, help="Maximum tool/model iterations per request.")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Maximum model output tokens per step.")
    parser.add_argument("--allowed-tool", dest="allowed_tools", action="append", default=[], help="Restrict this session to one allowed tool. Repeat for multiple tools.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature sent to Ollama.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Top-p sampling value sent to Ollama.")
    return parser


def interaction_mode(args):
    if getattr(args, "repl", False):
        return "repl"
    if getattr(args, "tui", False):
        return "tui"
    if getattr(args, "prompt", None):
        return "one_shot"
    return "tui"


def run_plain_repl(agent):
    while True:
        # 交互模式：每次读取一条用户输入，交给同一个 agent，
        # 因此 session history 和 working memory 会跨轮延续。
        try:
            user_input = input("\npico> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            return 0

        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            return 0
        if user_input == "/help":
            print(HELP_DETAILS)
            continue
        if user_input == "/memory":
            print(agent.memory_text())
            continue
        if user_input == "/session":
            print(agent.session_path)
            continue
        if user_input == "/tasks":
            print(agent.run_tool("todo_list", {}))
            continue
        if user_input == "/verify":
            task_state = agent.current_task_state
            plan = dict(getattr(task_state, "verification_plan", {}) or {}) if task_state is not None else {}
            if plan:
                print("verification plan:")
                for item in plan.get("requirements", []) or []:
                    print(f"- requirement {item.get('id', '')}: {item.get('reason', '')}")
                for item in plan.get("suggested_commands", []) or []:
                    print(f"- suggested `{item.get('command', '')}`: {item.get('reason', '')}")
                for item in plan.get("missing_evidence", []) or []:
                    print(f"- missing {item.get('requirement', '')}: {item.get('reason', '')}")
                action = select_verification_action(plan)
                if action:
                    action_args = action.get("args", {})
                    print(f"- next action `{action.get('name', '')}`: {action_args.get('command', '')}")
            graph = dict(getattr(task_state, "artifact_graph", {}) or {}) if task_state is not None else {}
            artifacts = list(graph.get("artifacts", []) or [])
            if artifacts:
                print("artifact status:")
                for item in artifacts[-10:]:
                    print(f"- {item.get('status', '')} {item.get('kind', '')} {item.get('path', '')}")
            verifications = list(getattr(task_state, "verifications", []) or []) if task_state is not None else []
            if not verifications:
                verifications = list(agent.session.get("verifications", []) or [])
            if not verifications:
                print("verification artifacts: none")
            for item in verifications[-10:]:
                print(f"{item.get('status', 'not_run')} exit={item.get('exit_code', '-')} {item.get('command', '')}")
            continue
        if user_input == "/skills":
            if not agent.feature_enabled("skills"):
                print("available skills: disabled")
                continue
            skills = [skill for skill in agent.skill_catalog.discover() if skill.user_invocable]
            if not skills:
                print("available skills: none")
            for skill in skills:
                command = skill.command_name()
                if skill.argument_hint:
                    command += f" <{skill.argument_hint}>"
                detail = f" — {skill.when_to_use}" if skill.when_to_use else ""
                print(f"{command}: {skill.description or '(no description)'}{detail}")
            continue
        if user_input == "/history":
            sessions = agent.session_store.list_sessions()
            if not sessions:
                print("no saved sessions")
            for index, session in enumerate(sessions[:20], start=1):
                current = " current" if session["id"] == agent.session["id"] else ""
                print(f"{index}. {session['id']}{current} messages={session['history_count']} mode={session['runtime_mode']}")
            continue
        if user_input.startswith("/resume"):
            _, _, query = user_input.partition(" ")
            query = query.strip()
            sessions = agent.session_store.list_sessions()
            session_id = ""
            try:
                index = int(query) - 1
                if 0 <= index < len(sessions):
                    session_id = sessions[index]["id"]
            except ValueError:
                matches = [session["id"] for session in sessions if session["id"].startswith(query)]
                session_id = matches[0] if len(matches) == 1 else ""
            if not session_id:
                print("usage: /resume <session-id|number>")
                continue
            agent.load_session(session_id)
            print(f"resumed session {session_id}")
            continue
        if user_input.startswith("/compact"):
            _, _, arg = user_input.partition(" ")
            try:
                keep_recent = int(arg.strip()) if arg.strip() else 6
            except ValueError:
                print("usage: /compact [recent-message-count]")
                continue
            result = agent.compact_history(keep_recent=keep_recent)
            if result["compacted"]:
                print(
                    f"compacted {result['before_messages']} -> {result['after_messages']} messages, "
                    f"~{result['before_tokens']} -> ~{result['after_tokens']} tokens"
                )
            else:
                print("compact skipped: too few messages")
            continue
        if user_input.startswith("/plan"):
            _, _, topic = user_input.partition(" ")
            plan_path = agent.enter_plan_mode(topic.strip())
            print(f"entered plan mode: {plan_path}")
            continue
        if user_input in {"/execute", "/exit-plan"}:
            if agent.runtime_mode != "plan":
                print("not in plan mode")
                continue
            plan_text = agent.exit_plan_mode()
            print("exited plan mode")
            if plan_text.strip():
                print(plan_text)
            continue
        if user_input == "/reset":
            agent.reset()
            print("session reset")
            continue

        print()
        try:
            print(agent.ask(user_input))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)


def main(argv=None):
    args = _normalize_provider_args(build_arg_parser().parse_args(argv))
    mode = interaction_mode(args)
    agent = build_agent(args)

    if mode == "tui":
        from .tui.app import PicoTuiApp

        PicoTuiApp(agent).run()
        return 0

    model = getattr(agent.model_client, "model", getattr(args, "model", DEFAULT_OLLAMA_MODEL))
    host = getattr(agent.model_client, "host", getattr(agent.model_client, "base_url", getattr(args, "host", DEFAULT_OLLAMA_HOST)))
    print(build_welcome(agent, model=model, host=host))

    if args.prompt:
        # one-shot 模式：只跑一次 ask，不进入 REPL 循环。
        prompt = " ".join(args.prompt).strip()
        if prompt:
            print()
            try:
                print(agent.ask(prompt))
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        return 0

    return run_plain_repl(agent)
