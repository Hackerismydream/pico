from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.picobench.packs.skill_transfer import campaign as skill_campaign
from benchmarks.picobench.packs.skill_transfer import candidate_worker
from benchmarks.picobench.packs.skill_transfer.campaign import (
    CampaignConfig,
    NegativeRecord,
    TrialRecord,
    build_report,
    corpus_split_digests,
    directory_digest,
    load_corpus,
    plan,
    run_campaign,
)
from benchmarks.picobench.packs.skill_transfer.fixtures import materialize, verify

CORPUS = Path("benchmarks/picobench/tasks/skill_transfer_v1.json")


def _candidate(corpus) -> dict:
    candidate = {
        "active_revisions": {
            ability.ability_id: f"skill_rev_{index:064x}" for index, ability in enumerate(corpus.abilities, 1)
        },
        "source_learning_instance_ids": {
            ability.ability_id: [item.instance_id for item in ability.learning] for ability in corpus.abilities
        },
        "source_experience_ids": {
            ability.ability_id: [f"mem_{ability.ability_id}_{index}" for index in range(3)]
            for ability in corpus.abilities
        },
    }
    candidate["learning_experience_maps"] = {
        ability.ability_id: dict(
            zip(
                (item.instance_id for item in ability.learning),
                candidate["source_experience_ids"][ability.ability_id],
                strict=True,
            )
        )
        for ability in corpus.abilities
    }
    candidate["candidate_input_digest"] = corpus_split_digests(corpus)["learning"]
    candidate["candidate_frozen_before_admission_precheck"] = True
    candidate["held_out_admission_precheck"] = {
        item.instance_id: [candidate["active_revisions"][ability.ability_id]]
        for ability in corpus.abilities
        for item in ability.held_out
    }
    return candidate


def _records(corpus, candidate, *, control_pass: bool = False):
    trials = []
    for ability in corpus.abilities:
        revision = candidate["active_revisions"][ability.ability_id]
        sources = tuple(candidate["source_experience_ids"][ability.ability_id])
        for task in ability.held_out:
            for repetition in range(2):
                digest = f"workspace:{task.instance_id}"
                trials.extend(
                    (
                        TrialRecord(
                            task_id=task.instance_id,
                            ability_id=ability.ability_id,
                            repetition=repetition,
                            arm_id="control",
                            status="passed" if control_pass else "task_failed",
                            workspace_digest=digest,
                            active_revision_id=None,
                            injected_skill_ids=(),
                            source_experience_ids=(),
                            tool_calls=3,
                            turns=1,
                            latency_ms=300,
                            input_tokens=900,
                            output_tokens=100,
                            provider_calls=3,
                            estimated_cost_cny=0.002,
                            verification_receipt=(
                                {
                                    "schema": "pico.picobench.skill-transfer.verification.v1",
                                    "fixture": task.fixture,
                                    "passed": True,
                                    "smoke_fixture_unchanged": True,
                                    "unexpected_workspace_paths": [],
                                }
                                if control_pass
                                else {"passed": False}
                            ),
                        ),
                        TrialRecord(
                            task_id=task.instance_id,
                            ability_id=ability.ability_id,
                            repetition=repetition,
                            arm_id="treatment",
                            status="passed",
                            workspace_digest=digest,
                            active_revision_id=revision,
                            injected_skill_ids=(revision,),
                            source_experience_ids=sources,
                            tool_calls=2,
                            turns=1,
                            latency_ms=250,
                            input_tokens=700,
                            output_tokens=80,
                            provider_calls=2,
                            estimated_cost_cny=0.0015,
                            verification_receipt={
                                "schema": "pico.picobench.skill-transfer.verification.v1",
                                "fixture": task.fixture,
                                "passed": True,
                                "smoke_fixture_unchanged": True,
                                "unexpected_workspace_paths": [],
                            },
                        ),
                    )
                )
    negatives = tuple(
        NegativeRecord(
            instance_id=item.instance_id,
            ability_id=ability.ability_id,
            active_revision_id=candidate["active_revisions"][ability.ability_id],
            recalled_revision_ids=(),
        )
        for ability in corpus.abilities
        for item in ability.hard_negatives
    )
    return tuple(trials), negatives


def test_frozen_corpus_is_instance_disjoint_and_has_exact_counts() -> None:
    corpus = load_corpus(CORPUS)

    assert len(corpus.abilities) == 6
    assert sum(len(item.learning) for item in corpus.abilities) == 18
    assert sum(len(item.held_out) for item in corpus.abilities) == 24
    assert sum(len(item.hard_negatives) for item in corpus.abilities) == 24


def test_report_requires_all_pairs_provenance_negatives_and_positive_clustered_ci() -> None:
    corpus = load_corpus(CORPUS)
    candidate = _candidate(corpus)
    trials, negatives = _records(corpus, candidate)

    report = build_report(
        corpus=corpus,
        trials=trials,
        negatives=negatives,
        candidate_receipt=candidate,
        bootstrap_samples=200,
    )

    assert report["measurement"] == {
        "planned_pairs": 48,
        "complete_pairs": 48,
        "valid_pairs": 48,
        "axis_valid": True,
        "instance_disjoint": True,
        "provenance_complete": True,
        "resource_observations_complete": True,
        "verification_receipts_valid": True,
        "candidate_input_sealed": True,
        "admission_precheck_complete": True,
    }
    assert report["capability"]["verified_pass_delta_pp"] == 100.0
    assert report["capability"]["task_clustered_bootstrap_95_ci"]["lower"] == 1.0
    assert report["safety"]["incorrect_skill_injections"] == 0
    assert report["claim"]["positive_claim_eligible"] is True


def test_one_wrong_hard_negative_blocks_positive_claim() -> None:
    corpus = load_corpus(CORPUS)
    candidate = _candidate(corpus)
    trials, negatives = _records(corpus, candidate)
    first = negatives[0]
    negatives = (
        NegativeRecord(
            instance_id=first.instance_id,
            ability_id=first.ability_id,
            active_revision_id=first.active_revision_id,
            recalled_revision_ids=(first.active_revision_id,),
        ),
        *negatives[1:],
    )

    report = build_report(
        corpus=corpus, trials=trials, negatives=negatives, candidate_receipt=candidate, bootstrap_samples=20
    )

    assert report["claim"]["measurement_valid"] is True
    assert report["safety"]["incorrect_skill_injections"] == 1
    assert report["claim"]["positive_claim_eligible"] is False


def test_forged_pass_without_independent_receipt_invalidates_measurement() -> None:
    corpus = load_corpus(CORPUS)
    candidate = _candidate(corpus)
    trials, negatives = _records(corpus, candidate)
    first = trials[1]
    trials = (
        trials[0],
        replace(first, verification_receipt={"passed": True}),
        *trials[2:],
    )

    report = build_report(
        corpus=corpus, trials=trials, negatives=negatives, candidate_receipt=candidate, bootstrap_samples=20
    )

    assert report["measurement"]["verification_receipts_valid"] is False
    assert report["claim"]["measurement_valid"] is False


def test_learning_to_experience_mapping_is_required_for_provenance() -> None:
    corpus = load_corpus(CORPUS)
    candidate = _candidate(corpus)
    trials, negatives = _records(corpus, candidate)
    first = corpus.abilities[0]
    candidate["learning_experience_maps"][first.ability_id].pop(first.learning[0].instance_id)

    report = build_report(
        corpus=corpus, trials=trials, negatives=negatives, candidate_receipt=candidate, bootstrap_samples=20
    )

    assert report["measurement"]["provenance_complete"] is False
    assert report["claim"]["measurement_valid"] is False


def test_candidate_input_must_bind_learning_only_projection() -> None:
    corpus = load_corpus(CORPUS)
    candidate = _candidate(corpus)
    trials, negatives = _records(corpus, candidate)
    candidate["candidate_input_digest"] = corpus_split_digests(corpus)["held_out"]

    report = build_report(
        corpus=corpus, trials=trials, negatives=negatives, candidate_receipt=candidate, bootstrap_samples=20
    )

    assert report["measurement"]["candidate_input_sealed"] is False
    assert report["claim"]["measurement_valid"] is False


def test_candidate_admission_precheck_must_recall_exact_revision() -> None:
    corpus = load_corpus(CORPUS)
    candidate = _candidate(corpus)
    trials, negatives = _records(corpus, candidate)
    task = corpus.abilities[0].held_out[0]
    candidate["held_out_admission_precheck"][task.instance_id] = []

    report = build_report(
        corpus=corpus, trials=trials, negatives=negatives, candidate_receipt=candidate, bootstrap_samples=20
    )

    assert report["measurement"]["admission_precheck_complete"] is False
    assert report["claim"]["measurement_valid"] is False


def test_plan_freezes_candidate_budget_and_requires_exact_wheels(tmp_path: Path) -> None:
    pico = tmp_path / "pico.whl"
    myna = tmp_path / "myna.whl"
    pico.write_bytes(b"pico")
    myna.write_bytes(b"myna")
    config = CampaignConfig(
        corpus_path=CORPUS,
        output_root=tmp_path / "evidence",
        pico_wheel=pico,
        myna_wheel=myna,
        pico_commit="a" * 40,
        myna_commit="b" * 40,
    )

    frozen = plan(config)

    assert frozen["manifest"]["execution"]["planned_primary_pairs"] == 48
    assert frozen["manifest"]["execution"]["planned_primary_trials"] == 96
    assert frozen["manifest"]["sealed_inputs"]["candidate_worker_receives_learning_projection_only"] is True
    assert frozen["manifest"]["budget"]["maximum_cost_cny"] <= 25
    assert len(frozen["approval_digest"]) == 64


def test_corpus_rejects_cross_split_identity_reuse(tmp_path: Path) -> None:
    raw = CORPUS.read_text(encoding="utf-8").replace('"eval-config-01"', '"learn-config-01"', 1)
    path = tmp_path / "overlap.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(ValueError, match="must be disjoint"):
        load_corpus(path)


def test_candidate_runtime_directory_digest_binds_paths_and_bytes(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "state.sqlite3").write_bytes(b"first")
    before = directory_digest(runtime)
    (runtime / "state.sqlite3").write_bytes(b"second")

    assert directory_digest(runtime) != before


def test_artifact_inventory_detects_raw_outcome_mutation(tmp_path: Path) -> None:
    for relative in skill_campaign._ARTIFACT_PATHS:
        (tmp_path / relative).write_text(f"{relative}\n", encoding="utf-8")
    skill_campaign._write_json(
        tmp_path / "inventory.json",
        {
            "schema": "pico.picobench.skill-transfer.inventory.v1",
            "files": [
                {"path": relative, "sha256": skill_campaign._sha256(tmp_path / relative)}
                for relative in skill_campaign._ARTIFACT_PATHS
            ],
        },
    )

    skill_campaign._verify_inventory(tmp_path)
    (tmp_path / "raw-outcomes.jsonl").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="digest changed"):
        skill_campaign._verify_inventory(tmp_path)


async def test_candidate_retry_tick_is_not_a_verified_learning_experience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Backend:
        def __init__(self) -> None:
            self.stored = None
            self.signals = None

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def store(self, session_id, messages) -> None:
            self.stored = (session_id, messages)

        async def feedback(self, signals) -> None:
            self.signals = signals

    backend = Backend()
    monkeypatch.setattr(candidate_worker, "_backend", lambda _repository: backend)

    await candidate_worker._retry_pending(tmp_path, "config_precedence")

    assert backend.stored[1][0]["content"] != "Implement explicit configuration precedence with absent-value fallback."
    assert backend.signals["verifications"] == [
        {"check_name": "candidate-extraction-retry-tick", "outcome": "failure", "call_id": None}
    ]


def test_paid_run_rejects_missing_exact_approval_before_installing(tmp_path: Path) -> None:
    pico = tmp_path / "pico.whl"
    myna = tmp_path / "myna.whl"
    pico.write_bytes(b"pico")
    myna.write_bytes(b"myna")
    config = CampaignConfig(
        corpus_path=CORPUS,
        output_root=tmp_path / "evidence",
        pico_wheel=pico,
        myna_wheel=myna,
        pico_commit="a" * 40,
        myna_commit="b" * 40,
    )

    with pytest.raises(ValueError, match="exact frozen approval"):
        run_campaign(
            config,
            approval_digest="wrong",
            approved_cny=25,
            execute_paid=True,
            provider_api_key="unused",
            provider_api_base=None,
        )


@pytest.mark.parametrize("ability_index", range(6))
def test_hidden_fixture_verifier_accepts_reference_implementation(tmp_path: Path, ability_index: int) -> None:
    corpus = load_corpus(CORPUS)
    ability = corpus.abilities[ability_index]
    reference = {
        "config_precedence": "def resolve(cli, env, project, default):\n    return next((v for v in (cli, env, project, default) if v is not None), None)\n",
        "retry_after": (
            "import datetime as dt\nfrom email.utils import parsedate_to_datetime\n"
            "def retry_delay(header, *, now, attempt, minimum, maximum):\n"
            "    try:\n"
            "        value = int(header)\n"
            "    except (TypeError, ValueError):\n"
            "        try: value = parsedate_to_datetime(header).timestamp() - now\n"
            "        except (TypeError, ValueError, OverflowError): value = minimum * 2 ** attempt\n"
            "    return max(minimum, min(maximum, round(value)))\n"
        ),
        "atomic_json": (
            "import json, os, tempfile\nfrom pathlib import Path\n"
            "def write_json(path, value):\n"
            "    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = None\n"
            "    try:\n"
            "        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')\n"
            "        with os.fdopen(fd, 'w') as handle:\n"
            "            json.dump(value, handle, sort_keys=True, separators=(',', ':')); handle.write('\\n'); handle.flush(); os.fsync(handle.fileno())\n"
            "        os.replace(temporary, path); temporary = None\n"
            "    finally:\n"
            "        if temporary is not None:\n"
            "            try: os.unlink(temporary)\n"
            "            except FileNotFoundError: pass\n"
        ),
        "jsonl_dedup": (
            "import json\n"
            "def aggregate(paths, *, identity_fields, keep='first'):\n"
            "    records = {}; order = []; invalid = 0; conflicts = []\n"
            "    for path in paths:\n"
            "        for line in path.read_text().splitlines():\n"
            "            try: item = json.loads(line)\n"
            "            except ValueError: invalid += 1; continue\n"
            "            key = tuple(item.get(field) for field in identity_fields)\n"
            "            if key in records:\n"
            "                if records[key] != item: conflicts.append(key)\n"
            "                if keep == 'last': records[key] = item\n"
            "            else: records[key] = item; order.append(key)\n"
            "    return {'records':[records[key] for key in order], 'invalid_lines':invalid, 'conflicts':conflicts}\n"
        ),
        "path_containment": (
            "from pathlib import Path\n"
            "def safe_path(workspace, candidate, *, allow_root=False):\n"
            "    root = Path(workspace).resolve(); path = Path(candidate); path = path.resolve() if path.is_absolute() else (root / path).resolve()\n"
            "    if path == root and allow_root: return path\n"
            "    if path == root or not path.is_relative_to(root): raise ValueError('outside workspace')\n"
            "    return path\n"
        ),
        "async_cleanup": (
            "async def run_managed(factories, body):\n"
            "    resources = []; primary = None; result = None\n"
            "    try:\n"
            "        for factory in factories: resources.append(await factory())\n"
            "        result = await body(resources)\n"
            "    except BaseException as error: primary = error\n"
            "    close_error = None\n"
            "    for resource in reversed(resources):\n"
            "        try: await resource.close()\n"
            "        except BaseException as error:\n"
            "            if close_error is None: close_error = error\n"
            "    if primary is not None: raise primary\n"
            "    if close_error is not None: raise close_error\n"
            "    return result\n"
        ),
    }[ability.ability_id]
    for task in ability.held_out:
        workspace = tmp_path / task.instance_id
        workspace.mkdir()
        materialize(workspace, task.fixture)
        (workspace / "solution.py").write_text(reference, encoding="utf-8")

        assert verify(workspace, task.fixture)["passed"] is True
