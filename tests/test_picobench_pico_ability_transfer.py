from __future__ import annotations

from pathlib import Path

from benchmarks.picobench.packs.skill_transfer.campaign import load_corpus
from benchmarks.picobench.packs.skill_transfer.fixtures import materialize, verify
from benchmarks.picobench.packs.skill_transfer_v2.stage_a import (
    _apply_pico_policy_execution_contract,
    anchor_content,
)

CORPUS = Path("benchmarks/picobench/tasks/pico_ability_transfer_v1.json")


def test_pico_policy_anchor_uses_learning_evidence_without_held_out_content() -> None:
    ability = load_corpus(CORPUS).abilities[0]

    body = anchor_content(ability, profile="pico_policy")

    assert ability.goal in body
    assert all(item.result in body and item.verification in body for item in ability.learning)
    assert all(item.prompt not in body for item in ability.held_out)
    assert "Trigger" in body
    assert "Procedure and boundaries" in body
    assert "Verification evidence" in body


def test_pico_policy_execution_contract_uses_inline_memory_skill_body() -> None:
    spec = {
        "prompt": "Implement the requested policy.",
        "disabled_tools": ["ask_user"],
    }

    contracted = _apply_pico_policy_execution_contract(spec)

    assert contracted is spec
    assert contracted["disabled_tools"] == ["ask_user", "find", "grep", "list_dir", "skill_read"]
    assert "already inline under # Skills" in contracted["prompt"]
    assert "replace the stub" in contracted["prompt"]
    assert "run smoke.py" in contracted["prompt"]
    assert "Do not explain or print a proposed implementation" in contracted["prompt"]
    assert "call edit_file" in contracted["prompt"]


def test_verification_learning_evidence_names_the_supported_ruff_actions() -> None:
    ability = load_corpus(CORPUS).abilities[0]

    evidence = "\n".join(item.result for item in ability.learning)

    assert "ruff check and ruff format" in evidence
    assert "ruff --version" in evidence


def test_verification_receipt_held_out_fixtures_accept_the_pico_policy(tmp_path: Path) -> None:
    ability = load_corpus(CORPUS).abilities[0]
    solution = """
import shlex
from pathlib import PurePath

def verification_name(command):
    if any(operator in command for operator in ("&&", "||", ";", "|", "&", "\\n", "\\r")):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    if not tokens:
        return None
    executable = PurePath(tokens[0]).name
    if executable in {"pytest", "mypy", "tox", "nox"}:
        return executable
    if executable == "ruff" and len(tokens) > 1 and tokens[1] in {"check", "format"}:
        return executable
    if executable == "make" and any(item in {"check", "ci", "lint", "test"} for item in tokens[1:]):
        return executable
    if executable in {"npm", "pnpm", "yarn", "bun"} and len(tokens) > 1:
        if tokens[1] == "test" or tokens[1:3] in (["run", "build"], ["run", "test"]):
            return executable
    if executable == "cargo" and len(tokens) > 1 and tokens[1] in {"build", "check", "test"}:
        return executable
    if executable == "go" and len(tokens) > 1 and tokens[1] in {"build", "test", "vet"}:
        return executable
    if executable in {"gradle", "gradlew", "mvn", "mvnw"}:
        return executable
    return None
"""

    for task in ability.held_out:
        workspace = tmp_path / task.instance_id
        workspace.mkdir()
        materialize(workspace, task.fixture)
        (workspace / "solution.py").write_text(solution, encoding="utf-8")

        assert verify(workspace, task.fixture)["passed"] is True


def test_derived_skill_held_out_fixtures_accept_the_fail_closed_policy(tmp_path: Path) -> None:
    ability = load_corpus(CORPUS).abilities[1]
    solution = """
def select_skills(candidates, selected_ids=None, *, gate_failed=False, max_select=2, legacy_top_k=5):
    local = [item for item in candidates if not item.get("gate_required")]
    if gate_failed or selected_ids is None:
        return [item["id"] for item in local[:legacy_top_k]]
    by_id = {item["id"]: item for item in candidates}
    if any(skill_id not in by_id for skill_id in selected_ids):
        return [item["id"] for item in local[:legacy_top_k]]
    admitted = set(selected_ids[:max_select])
    return [
        item["id"]
        for item in candidates
        if not item.get("gate_required") or item["id"] in admitted
    ]
"""

    for task in ability.held_out:
        workspace = tmp_path / task.instance_id
        workspace.mkdir()
        materialize(workspace, task.fixture)
        (workspace / "solution.py").write_text(solution, encoding="utf-8")

        assert verify(workspace, task.fixture)["passed"] is True


def test_checkpoint_held_out_fixtures_accept_the_invocation_policy(tmp_path: Path) -> None:
    ability = load_corpus(CORPUS).abilities[2]
    solution = """
def checkpoint_active(policy, *, interactive):
    if policy == "never":
        return False
    if policy == "always":
        return True
    if policy == "interactive":
        return interactive
    raise ValueError("unsupported checkpoint policy")
"""

    for task in ability.held_out:
        workspace = tmp_path / task.instance_id
        workspace.mkdir()
        materialize(workspace, task.fixture)
        (workspace / "solution.py").write_text(solution, encoding="utf-8")

        assert verify(workspace, task.fixture)["passed"] is True


def test_source_isolation_held_out_fixtures_preserve_healthy_results(tmp_path: Path) -> None:
    ability = load_corpus(CORPUS).abilities[3]
    solution = """
def isolate_sources(sources):
    hits = []
    failed_sources = []
    failure_types = {}
    for source in sources:
        error_type = source.get("error_type")
        if error_type:
            failed_sources.append(source["name"])
            failure_types[source["name"]] = error_type
        else:
            hits.extend(source.get("hits", []))
    return {
        "hits": hits,
        "failed_sources": failed_sources,
        "failure_types": failure_types,
    }
"""

    for task in ability.held_out:
        workspace = tmp_path / task.instance_id
        workspace.mkdir()
        materialize(workspace, task.fixture)
        (workspace / "solution.py").write_text(solution, encoding="utf-8")

        assert verify(workspace, task.fixture)["passed"] is True


def test_delivery_held_out_fixtures_keep_runtime_and_outlet_facts_separate(tmp_path: Path) -> None:
    ability = load_corpus(CORPUS).abilities[4]
    solution = """
def delivery_outcome(*, runner_state, outlet_matches, emitted, outlet_accepted):
    if not outlet_matches:
        return "no_outlet"
    if runner_state == "completed" and emitted and outlet_accepted:
        return "delivered"
    return "dropped"
"""

    for task in ability.held_out:
        workspace = tmp_path / task.instance_id
        workspace.mkdir()
        materialize(workspace, task.fixture)
        (workspace / "solution.py").write_text(solution, encoding="utf-8")

        assert verify(workspace, task.fixture)["passed"] is True


def test_activation_held_out_fixtures_require_evidence_and_human_authority(tmp_path: Path) -> None:
    ability = load_corpus(CORPUS).abilities[5]
    solution = """
def activation_state(candidate_kind, *, train_promoted, sealed_credited, human_approved):
    if candidate_kind != "runtime" or not train_promoted or not sealed_credited:
        return "ineligible"
    if not human_approved:
        return "pending_human"
    return "ready"
"""

    for task in ability.held_out:
        workspace = tmp_path / task.instance_id
        workspace.mkdir()
        materialize(workspace, task.fixture)
        (workspace / "solution.py").write_text(solution, encoding="utf-8")

        assert verify(workspace, task.fixture)["passed"] is True
