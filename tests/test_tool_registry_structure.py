from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.tools import registry
from pico.tools.spec import ToolSpec


def build_agent(tmp_path, outputs=None, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return Pico(
        model_client=FakeModelClient(outputs or []),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


def test_tool_registry_is_thin_spec_collector():
    specs = registry.all_tool_specs()
    names = {spec.name for spec in specs}

    assert all(isinstance(spec, ToolSpec) for spec in specs)
    assert {"list_files", "read_file", "glob", "grep", "run_shell", "todo_write", "agent"} <= names
    assert len(names) == len(specs)
    assert not hasattr(registry, "TOOL_DEFS")
    assert not hasattr(registry, "_TOOL_RUNNERS")


def test_tool_specs_materialize_existing_runtime_protocol(tmp_path):
    agent = build_agent(tmp_path, [])
    read_tool = agent.tools["read_file"]
    grep_tool = agent.tools["grep"]

    assert read_tool["schema"] == {"path": "str", "start": "int=1", "end": "int=200"}
    assert read_tool["read_only"] is True
    assert read_tool["policy"]["records_read"] is True
    assert read_tool["activity"] == "Reading ."
    assert grep_tool["read_only"] is True
    assert grep_tool["policy"]["concurrency"] == "parallel"
