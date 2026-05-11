import inspect


def test_policy_engine_returns_structured_tool_decision():
    from pico.core.policy_engine import PolicyDecision, PolicyEngine, ToolRequest

    decision = PolicyEngine().before_tool(None, ToolRequest(name="read_file", args={"path": "README.md"}, tool={"risky": False}))

    assert isinstance(decision, PolicyDecision)
    assert decision.allowed is True
    assert decision.to_preflight().allowed is True


def test_pico_preflight_delegates_to_policy_engine():
    import pico.core.agent as agent_module

    source = inspect.getsource(agent_module.Pico.preflight_tool)

    assert "policy_engine.before_tool" in source
    assert len(source.splitlines()) <= 12
