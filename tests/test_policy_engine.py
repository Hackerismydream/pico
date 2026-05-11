import inspect


def test_policy_engine_returns_structured_tool_decision():
    from pico.core.policy_engine import PolicyContext, PolicyDecision, PolicyEngine, ToolRequest

    context = PolicyContext(
        runtime_mode="execute",
        read_only=False,
        approval_policy="never",
        allowed_tools=None,
        write_scope=(),
        recent_tool_calls=[],
        read_ledger={},
        active_plan_file="",
        tools={"read_file": {"risky": False, "read_only": True, "policy": {}}},
    )
    decision = PolicyEngine().before_tool(context, ToolRequest(name="read_file", args={"path": "README.md"}, tool=context.tools["read_file"]))

    assert isinstance(decision, PolicyDecision)
    assert decision.allowed is True
    assert decision.to_preflight().allowed is True


def test_pico_preflight_delegates_to_policy_engine():
    import pico.core.agent as agent_module

    source = inspect.getsource(agent_module.Pico.preflight_tool)

    assert "policy_engine.before_tool" in source
    assert len(source.splitlines()) <= 12


def test_policy_engine_rejects_repeated_identical_call_from_context():
    from pico.core.policy_engine import PolicyContext, PolicyEngine, ToolRequest

    context = PolicyContext(
        runtime_mode="execute",
        read_only=False,
        approval_policy="never",
        allowed_tools=None,
        write_scope=(),
        recent_tool_calls=[
            {"name": "read_file", "args": {"path": "README.md"}},
            {"name": "read_file", "args": {"path": "README.md"}},
        ],
        read_ledger={},
        active_plan_file="",
        tools={"read_file": {"risky": False, "read_only": True, "policy": {}}},
    )

    decision = PolicyEngine().before_tool(
        context,
        ToolRequest(name="read_file", args={"path": "README.md"}, tool=context.tools["read_file"]),
    )

    assert decision.allowed is False
    assert decision.code == "repeated_identical_call"
    assert "repeated identical tool call" in decision.message


def test_policy_engine_rejects_non_plan_write_in_plan_mode():
    from pico.core.policy_engine import PolicyContext, PolicyEngine, ToolRequest

    tool = {"risky": True, "read_only": False, "policy": {}}
    context = PolicyContext(
        runtime_mode="plan",
        read_only=False,
        approval_policy="auto",
        allowed_tools=None,
        write_scope=(),
        recent_tool_calls=[],
        read_ledger={},
        active_plan_file=".pico/plans/plan-1.md",
        tools={"write_file": tool},
    )

    decision = PolicyEngine().before_tool(context, ToolRequest(name="write_file", args={"path": "README.md"}, tool=tool))

    assert decision.allowed is False
    assert decision.code == "plan_mode_denied"
    assert "active plan file" in decision.recovery_message


def test_policy_engine_rejects_missing_prior_read_from_context():
    from pico.core.policy_engine import PolicyContext, PolicyEngine, ToolRequest

    tool = {"risky": True, "read_only": False, "policy": {"requires_prior_read": True}}
    context = PolicyContext(
        runtime_mode="execute",
        read_only=False,
        approval_policy="auto",
        allowed_tools=None,
        write_scope=(),
        recent_tool_calls=[],
        read_ledger={},
        active_plan_file="",
        tools={"patch_file": tool},
        request_paths=("src/app.py",),
        path_freshness={"src/app.py": "fresh"},
    )

    decision = PolicyEngine().before_tool(context, ToolRequest(name="patch_file", args={"path": "src/app.py"}, tool=tool))

    assert decision.allowed is False
    assert decision.code == "prior_read_required"
    assert 'read_file with path "src/app.py"' in decision.recovery_message


def test_policy_engine_rejects_denied_approval_from_context():
    from pico.core.policy_engine import PolicyContext, PolicyEngine, ToolRequest

    tool = {"risky": True, "read_only": False, "policy": {}}
    context = PolicyContext(
        runtime_mode="execute",
        read_only=False,
        approval_policy="ask",
        allowed_tools=None,
        write_scope=(),
        recent_tool_calls=[],
        read_ledger={},
        active_plan_file="",
        tools={"run_shell": tool},
        approval_granted=False,
    )

    decision = PolicyEngine().before_tool(context, ToolRequest(name="run_shell", args={"command": "rm -rf build"}, tool=tool))

    assert decision.allowed is False
    assert decision.code == "approval_denied"
    assert decision.to_preflight().code == "approval_denied"
