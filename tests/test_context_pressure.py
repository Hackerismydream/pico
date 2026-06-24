from pico.testing import ScriptedModelClient
from pico import Pico, SessionStore, WorkspaceContext
from pico.core.context_manager import ContextManager
from pico.core.context_pressure import measure_pressure


def build_agent(tmp_path, outputs=None, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        model_client=ScriptedModelClient(outputs or []),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        **kwargs,
    )


def test_measure_pressure_tier0():
    pressure = measure_pressure(prompt_chars=59, total_budget=100)

    assert pressure.ratio == 0.59
    assert pressure.tier == "tier0_observe"
    assert pressure.source == "char_estimate"


def test_measure_pressure_tier1():
    assert measure_pressure(prompt_chars=60, total_budget=100).tier == "tier1_snip"
    assert measure_pressure(prompt_chars=79, total_budget=100).tier == "tier1_snip"


def test_measure_pressure_tier2():
    assert measure_pressure(prompt_chars=80, total_budget=100).tier == "tier2_prune"
    assert measure_pressure(prompt_chars=94, total_budget=100).tier == "tier2_prune"


def test_measure_pressure_tier3():
    assert measure_pressure(prompt_chars=95, total_budget=100).tier == "tier3_summary"
    assert measure_pressure(prompt_chars=140, total_budget=100).tier == "tier3_summary"


def test_measure_pressure_zero_budget():
    pressure = measure_pressure(prompt_chars=1, total_budget=0)

    assert pressure.ratio == 1.0
    assert pressure.tier == "tier3_summary"


def test_tier0_no_prompt_drift(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.record({"role": "user", "content": "old request"})
    agent.record({"role": "assistant", "content": "old answer"})

    manager = ContextManager(agent, total_budget=20000)
    prompt, metadata = manager.build("current request")

    assert prompt.rstrip().endswith("Current user request:\ncurrent request")
    assert metadata["pressure"]["tier"] == "tier0_observe"
    assert "old request" in prompt
    assert "old answer" in prompt


def test_tier1_reduces_relevant_memory_budget_and_history_window(tmp_path):
    agent = build_agent(tmp_path, [])
    for i in range(6):
        agent.record({"role": "user", "content": f"turn-{i} " + ("x" * 120)})
    for i in range(3):
        agent.memory.append_note("needle note " + ("m" * 300), tags=("needle",))

    manager = ContextManager(
        agent,
        total_budget=2000,
        section_budgets={
            "prefix": 80,
            "memory": 80,
            "skills": 80,
            "relevant_memory": 300,
            "history": 800,
        },
    )
    _, metadata = manager.build("needle")

    assert metadata["pressure"]["tier"] == "tier1_snip"
    assert metadata["section_budgets"]["relevant_memory"] == 210
    assert metadata["history"]["recent_window"] == 2


def test_tier2_reduces_skills_budget_and_prunes_history(tmp_path):
    agent = build_agent(tmp_path, [])
    for i in range(8):
        agent.record({"role": "user", "content": f"turn-{i} " + ("x" * 160)})
    for i in range(3):
        agent.memory.append_note("needle note " + ("m" * 400), tags=("needle",))

    manager = ContextManager(
        agent,
        total_budget=1800,
        section_budgets={
            "prefix": 80,
            "memory": 80,
            "skills": 120,
            "relevant_memory": 300,
            "history": 1100,
        },
        section_floors={
            "skills": 20,
            "relevant_memory": 20,
        },
    )
    _, metadata = manager.build("needle")

    assert metadata["pressure"]["tier"] == "tier2_prune"
    assert metadata["section_budgets"]["skills"] == 60
    assert metadata["history"]["recent_window"] == 2
    assert metadata["history"]["old_turn_line_limit"] == 40
