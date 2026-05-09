def test_cc_mini_style_package_boundaries_are_importable():
    from pico import MiniAgent, Pico, SessionStore
    from pico.commands.slash import resolve_command
    from pico.core.agent import Pico as CorePico
    from pico.core.model_decision import ModelDecisionAdapter
    from pico.core.runtime_events import RuntimeEvents
    from pico.core.session import SessionStore as CoreSessionStore
    from pico.core.state import RunContext, TaskState
    from pico.core.tool_runner import ToolRunner
    from pico.features.compact import CompactService
    from pico.features.context import ContextManager, build_context_usage
    from pico.providers.clients import FakeModelClient
    from pico.tools.registry import build_tool_registry
    from pico.tools.shell_safety import is_read_only_shell_command

    assert CorePico is Pico
    assert MiniAgent is Pico
    assert CoreSessionStore is SessionStore
    assert ModelDecisionAdapter is not None
    assert RuntimeEvents is not None
    assert TaskState is not None
    assert ToolRunner is not None
    assert RunContext is not None
    assert CompactService is not None
    assert ContextManager is not None
    assert build_context_usage is not None
    assert FakeModelClient is not None
    assert build_tool_registry is not None
    assert is_read_only_shell_command("pwd") is True
    assert resolve_command("compact").name == "compact"


def test_session_store_lives_in_core_session_not_agent_alias():
    from pathlib import Path

    source = Path("pico/core/session.py").read_text(encoding="utf-8")

    assert "class SessionStore" in source
    assert "from .agent import SessionStore" not in source


def test_setuptools_discovers_pico_subpackages():
    import tomllib
    from pathlib import Path

    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    find_config = config["tool"]["setuptools"]["packages"]["find"]

    assert "pico*" in find_config["include"]


def test_top_level_compatibility_facades_are_removed():
    from pathlib import Path

    facade_paths = [
        "pico/artifacts.py",
        "pico/compact.py",
        "pico/completion.py",
        "pico/context_manager.py",
        "pico/context_usage.py",
        "pico/memory.py",
        "pico/models.py",
        "pico/provider_adapter.py",
        "pico/run_context.py",
        "pico/run_store.py",
        "pico/runtime.py",
        "pico/runtime_control.py",
        "pico/shell_safety.py",
        "pico/skills.py",
        "pico/subagents.py",
        "pico/task_state.py",
        "pico/tui/commands.py",
        "pico/verifier_driver.py",
        "pico/workspace.py",
    ]

    assert [path for path in facade_paths if Path(path).exists()] == []
