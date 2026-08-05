from __future__ import annotations

import hashlib
import http.server
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import zipfile
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Any

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PINNED_INSTALL_RE = re.compile(r"@[0-9a-f]{40}$")
_EXPECTED_CONTRACT = {
    "backend_factory": "codecairn.integrations.pico.backend:make_backend",
    "entry_point": {
        "group": "pico.plugins",
        "name": "codecairn",
        "value": "codecairn.integrations.pico",
    },
    "memory_backend": "codecairn",
    "plugin_id": "codecairn-memory",
    "resource_package": "codecairn.integrations.pico",
    "source_schema": "codecairn.pico.source.v1",
    "turn_boundary": "pico_turn_end",
}


class PairIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PairAudit:
    pico_commit: str
    codecairn_commit: str
    codecairn_install_spec: str
    current_pico_wheel_sha256: str
    pico_distribution_report_sha256: str
    pico_source_manifest_sha256: str
    codecairn_wheel_sha256: str
    pico_handoff_sha256: str
    codecairn_handoff_sha256: str
    historical_pico_commits: dict[str, str]
    historical_pico_wheel_sha256: dict[str, str]
    plugin_contract: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "codecairn": {
                "commit": self.codecairn_commit,
                "install_spec": self.codecairn_install_spec,
                "wheel_sha256": self.codecairn_wheel_sha256,
            },
            "current_pico": {
                "commit": self.pico_commit,
                "distribution_report_sha256": self.pico_distribution_report_sha256,
                "source_manifest_sha256": self.pico_source_manifest_sha256,
                "wheel_sha256": self.current_pico_wheel_sha256,
            },
            "handoffs": {
                "codecairn_sha256": self.codecairn_handoff_sha256,
                "pico_sha256": self.pico_handoff_sha256,
            },
            "historical_pico_commits": dict(self.historical_pico_commits),
            "historical_pico_wheel_sha256": dict(self.historical_pico_wheel_sha256),
            "plugin_contract": dict(self.plugin_contract),
        }


@dataclass(frozen=True)
class ContinuityGateResult:
    output_root: Path
    pair_manifest: Path
    summary: Path
    pair_manifest_sha256: str
    summary_sha256: str


def audit_pair_inputs(
    *,
    pico_wheel: Path,
    codecairn_wheel: Path,
    pico_handoff: Path,
    codecairn_handoff: Path,
    pico_implementation_wheel: Path,
    pico_compatibility_wheel: Path,
    pico_distribution_report: Path,
    pico_commit: str,
) -> PairAudit:
    if not _COMMIT_RE.fullmatch(pico_commit):
        raise PairIntegrityError("current Pico commit must be a 40-character SHA")
    pico_data = _load_handoff(
        pico_handoff,
        kind="pico.codecairn.implementation.handoff",
    )
    codecairn_data = _load_handoff(
        codecairn_handoff,
        kind="codecairn.pico.adapter.handoff",
    )
    pico_section = _mapping(pico_data, "pico")
    implementation_distribution = _mapping(pico_section, "distribution")
    pico_codecairn = _mapping(pico_data, "codecairn")
    codecairn_section = _mapping(codecairn_data, "codecairn")
    codecairn_distribution = _mapping(codecairn_section, "distribution")
    codecairn_pico = _mapping(codecairn_data, "pico")
    codecairn_pico_wheel = _mapping(codecairn_pico, "wheel")
    codecairn_wheel_record = _mapping(codecairn_section, "wheel")

    implementation_commit = _commit(
        pico_section.get("commit"),
        "Pico implementation handoff commit",
    )
    compatibility_commit = _commit(
        codecairn_pico.get("commit"),
        "CodeCairn compatibility Pico commit",
    )
    codecairn_commit = _commit(
        pico_codecairn.get("commit"),
        "Pico handoff CodeCairn commit",
    )
    if (
        _commit(
            codecairn_section.get("commit"),
            "CodeCairn handoff commit",
        )
        != codecairn_commit
    ):
        raise PairIntegrityError("CodeCairn handoffs disagree on commit")
    install_spec = _string(
        pico_codecairn.get("install_spec"),
        "Pico handoff CodeCairn install spec",
    )
    if (
        _string(
            codecairn_section.get("install_spec"),
            "CodeCairn handoff install spec",
        )
        != install_spec
        or not _PINNED_INSTALL_RE.search(install_spec)
        or not install_spec.endswith(codecairn_commit)
    ):
        raise PairIntegrityError("CodeCairn install specification is not immutable or consistent")

    current_pico_sha = _sha256(pico_wheel)
    distribution = _verify_pico_distribution_report(
        pico_distribution_report,
        pico_commit=pico_commit,
        pico_wheel_sha256=current_pico_sha,
    )
    codecairn_sha = _sha256(codecairn_wheel)
    implementation_sha = _sha256(pico_implementation_wheel)
    compatibility_sha = _sha256(pico_compatibility_wheel)
    expected_implementation_sha = _digest(
        implementation_distribution.get("wheel_sha256"),
        "Pico implementation wheel digest",
    )
    expected_compatibility_sha = _digest(
        codecairn_pico_wheel.get("sha256"),
        "CodeCairn compatibility Pico wheel digest",
    )
    expected_codecairn = {
        _digest(
            pico_codecairn.get("wheel_sha256"),
            "Pico handoff CodeCairn wheel digest",
        ),
        _digest(
            codecairn_wheel_record.get("sha256"),
            "CodeCairn handoff wheel digest",
        ),
    }
    if implementation_sha != expected_implementation_sha:
        raise PairIntegrityError("Pico implementation wheel digest mismatch")
    if compatibility_sha != expected_compatibility_sha:
        raise PairIntegrityError("CodeCairn compatibility Pico wheel digest mismatch")
    if expected_codecairn != {codecairn_sha}:
        raise PairIntegrityError("CodeCairn wheel digest mismatch")
    codecairn_handoff_sha = _sha256(codecairn_handoff)
    if (
        _digest(
            pico_codecairn.get("handoff_sha256"),
            "CodeCairn handoff digest",
        )
        != codecairn_handoff_sha
    ):
        raise PairIntegrityError("CodeCairn handoff digest mismatch")

    current_pico_metadata = _wheel_metadata(pico_wheel)
    implementation_metadata = _wheel_metadata(pico_implementation_wheel)
    compatibility_metadata = _wheel_metadata(pico_compatibility_wheel)
    codecairn_metadata = _wheel_metadata(codecairn_wheel)
    expected_pico_identity = (
        _string(
            implementation_distribution.get("name"),
            "Pico distribution name",
        ),
        _string(
            implementation_distribution.get("version"),
            "Pico distribution version",
        ),
    )
    if {
        current_pico_metadata,
        implementation_metadata,
        compatibility_metadata,
    } != {expected_pico_identity}:
        raise PairIntegrityError("Pico wheel distribution identity mismatch")
    expected_codecairn_identity = (
        _string(
            pico_codecairn.get("distribution_name"),
            "CodeCairn distribution name",
        ),
        _string(
            pico_codecairn.get("distribution_version"),
            "CodeCairn distribution version",
        ),
    )
    if (
        expected_codecairn_identity
        != (
            _string(
                codecairn_distribution.get("name"),
                "CodeCairn handoff distribution name",
            ),
            _string(
                codecairn_distribution.get("version"),
                "CodeCairn handoff distribution version",
            ),
        )
        or codecairn_metadata != expected_codecairn_identity
    ):
        raise PairIntegrityError("CodeCairn wheel distribution identity mismatch")

    contract = _mapping(pico_data, "plugin_contract")
    if contract != _EXPECTED_CONTRACT:
        raise PairIntegrityError("Pico handoff Plugin contract is incompatible")
    _verify_plugin_inventory(codecairn_data, codecairn_wheel)
    return PairAudit(
        pico_commit=pico_commit,
        codecairn_commit=codecairn_commit,
        codecairn_install_spec=install_spec,
        current_pico_wheel_sha256=current_pico_sha,
        pico_distribution_report_sha256=_sha256(
            pico_distribution_report,
        ),
        pico_source_manifest_sha256=distribution["source_manifest_sha256"],
        codecairn_wheel_sha256=codecairn_sha,
        pico_handoff_sha256=_sha256(pico_handoff),
        codecairn_handoff_sha256=codecairn_handoff_sha,
        historical_pico_commits={
            "codecairn_compatibility": compatibility_commit,
            "pico_implementation": implementation_commit,
        },
        historical_pico_wheel_sha256={
            "codecairn_compatibility": compatibility_sha,
            "pico_implementation": implementation_sha,
        },
        plugin_contract=dict(contract),
    )


def run_continuity_gate(
    *,
    pico_wheel: Path,
    codecairn_wheel: Path,
    pico_handoff: Path,
    codecairn_handoff: Path,
    pico_implementation_wheel: Path,
    pico_compatibility_wheel: Path,
    pico_distribution_report: Path,
    pico_commit: str,
    pico_source_root: Path,
    codecairn_source_root: Path,
    output_root: Path,
) -> ContinuityGateResult:
    source_commit = _clean_source_commit(pico_source_root)
    if source_commit != pico_commit:
        raise PairIntegrityError("current Pico wheel commit does not match the clean source checkout")
    codecairn_source_commit = _clean_source_commit(
        codecairn_source_root,
        label="CodeCairn",
    )
    audit = audit_pair_inputs(
        pico_wheel=pico_wheel,
        codecairn_wheel=codecairn_wheel,
        pico_handoff=pico_handoff,
        codecairn_handoff=codecairn_handoff,
        pico_implementation_wheel=pico_implementation_wheel,
        pico_compatibility_wheel=pico_compatibility_wheel,
        pico_distribution_report=pico_distribution_report,
        pico_commit=pico_commit,
    )
    if codecairn_source_commit != audit.codecairn_commit:
        raise PairIntegrityError(
            "CodeCairn source checkout does not match the immutable handoff commit",
        )
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise PairIntegrityError("continuity output root must be empty")
    with tempfile.TemporaryDirectory(prefix="pico-codecairn-continuity-") as temporary:
        scratch = Path(temporary)
        environment = _install_pair(
            scratch,
            pico_wheel=pico_wheel,
            codecairn_wheel=codecairn_wheel,
        )
        worker = scratch / "codecairn_installed_worker.py"
        shutil.copy2(
            Path(__file__).with_name("codecairn_installed_worker.py"),
            worker,
        )
        python = environment / "bin" / "python"
        codecairn_cli = environment / "bin" / "codecairn"
        base_env = {
            **os.environ,
            "PYTHONPATH": "",
            "PICO_HOME": str(scratch / "identity-pico-home"),
        }
        identity = _worker(
            python,
            worker,
            {"worker_mode": "identity"},
            scratch / "identity",
            env=base_env,
        )
        _verify_installed_identity(
            identity,
            environment=environment,
            pico_source_root=pico_source_root,
            codecairn_source_root=codecairn_source_root,
        )
        with _LocalOpenAIProvider(scratch / "local-provider") as local_provider:
            provider_env = {
                **base_env,
                "CODECAIRN_SEMANTIC_API_KEY": "local-stage-a",
                "CODECAIRN_SEMANTIC_ENDPOINT": local_provider.endpoint,
                "CODECAIRN_SEMANTIC_MODEL": "joint-deterministic",
                "SSL_CERT_FILE": str(local_provider.certificate),
            }
            cases = _run_continuity_cases(
                scratch=scratch,
                python=python,
                worker=worker,
                codecairn_cli=codecairn_cli,
                env=provider_env,
                local_provider=local_provider,
            )
            if local_provider.external_calls != 0:
                raise PairIntegrityError("Stage A attempted a non-local external provider call")
            provider_receipt = local_provider.receipt()
        environment_digest = _digest_json(
            {
                "identity": identity,
                "platform": platform.platform(),
                "python": platform.python_version(),
            }
        )
        manifest_data = {
            "schema": "pico.codecairn.pair-manifest.v1",
            "audit": audit.as_dict(),
            "environment": {
                "digest": environment_digest,
                "installed": identity,
                "platform": platform.platform(),
                "python": platform.python_version(),
                "source_checkouts_absent": True,
            },
            "local_provider": provider_receipt,
        }
        pair_manifest = output_root / "pair-manifest.json"
        _write_json(pair_manifest, manifest_data)
        summary_data = {
            "schema": "pico.codecairn.continuity-summary.v1",
            "j0": {
                "pair_integrity": True,
                "source_checkouts_absent": True,
                "passed": True,
            },
            "j1": cases["j1"],
            "j2": cases["j2"],
            "passed": bool(cases["j1"].get("passed") and cases["j2"].get("passed")),
            "paid_external_calls": 0,
            "pair_manifest_sha256": _sha256(pair_manifest),
        }
        summary = output_root / "continuity-summary.json"
        _write_json(summary, summary_data)
        if summary_data["passed"] is not True:
            raise PairIntegrityError("installed continuity Gate did not pass")
        return ContinuityGateResult(
            output_root=output_root,
            pair_manifest=pair_manifest,
            summary=summary,
            pair_manifest_sha256=_sha256(pair_manifest),
            summary_sha256=_sha256(summary),
        )


def _run_continuity_cases(
    *,
    scratch: Path,
    python: Path,
    worker: Path,
    codecairn_cli: Path,
    env: dict[str, str],
    local_provider: _LocalOpenAIProvider,
) -> dict[str, dict[str, object]]:
    repository_a = scratch / "repository-a"
    repository_b = scratch / "repository-b"
    runtime_a = scratch / "runtime-a"
    runtime_b = runtime_a
    _init_git_repository(repository_a)
    _init_git_repository(repository_b)
    _seed_local_skill(repository_a)
    _seed_local_skill(repository_b)
    _init_codecairn(
        codecairn_cli,
        repository_a,
        runtime_a,
        "joint/repository-a",
        env,
    )
    _init_codecairn(
        codecairn_cli,
        repository_b,
        runtime_b,
        "joint/repository-b",
        env,
    )
    marker = "violet-cairn-9271"
    key = "release_phrase"
    conversation = "shared-conversation"
    base = {
        "conversation_id": conversation,
        "expected_key": key,
        "expected_value": marker,
        "message_id": "joint-message",
        "output_file": "result.json",
        "timeout_seconds": 60,
        "worker_mode": "turn",
    }
    learn = _worker(
        python,
        worker,
        {
            **base,
            "memory_enabled": True,
            "mode": "learn",
            "prompt": (f"Remember that {key} is {marker}. Confirm this repository-specific release fact."),
            "recall_observation": str(scratch / "learn-recall.json"),
            "workspace": str(repository_a),
        },
        scratch / "learn",
        env={**env, "PICO_HOME": str(scratch / "pico-home-learn")},
    )
    if not _clean_turn(learn, expected_backend=True):
        raise PairIntegrityError("installed learning Turn failed")
    process = _command_json(
        (
            str(codecairn_cli),
            "process",
            "--worker-id",
            "joint-stage-a",
            "--max-jobs",
            "8",
        ),
        cwd=repository_a,
        env=env,
    )
    semantic = process.get("semantic")
    if (
        not isinstance(semantic, dict)
        or semantic.get("completed") != 1
        or semantic.get("failed") != 0
        or semantic.get("pending") != 0
    ):
        raise PairIntegrityError("deterministic semantic completion did not close the pending job")
    expected_memories = _codecairn_list(codecairn_cli, repository_a, env)
    expected_ids = sorted(_memory_ids(expected_memories))
    if not expected_ids:
        raise PairIntegrityError("learning Turn produced no CodeCairn Memory")
    recall = _command_json(
        (
            str(codecairn_cli),
            "recall",
            key,
            "--limit",
            "5",
            "--format",
            "json",
        ),
        cwd=repository_a,
        env=env,
    )
    sidecar = recall.get("sidecar")
    if not isinstance(sidecar, dict) or sidecar.get("freshness") != "fresh":
        raise PairIntegrityError("CodeCairn recall remained semantic_pending")
    evaluation_observation = scratch / "evaluation-recall.json"
    evaluation = _worker(
        python,
        worker,
        {
            **base,
            "memory_enabled": True,
            "mode": "evaluate",
            "prompt": (f"Recover {key} from repository Memory and write result.json."),
            "recall_observation": str(evaluation_observation),
            "workspace": str(repository_a),
        },
        scratch / "evaluate",
        env={**env, "PICO_HOME": str(scratch / "pico-home-evaluate")},
    )
    observed_recall = _read_json(evaluation_observation)
    output_a = _read_json(repository_a / "result.json")
    if (
        not _clean_turn(evaluation, expected_backend=True)
        or output_a != {key: marker}
        or evaluation["outcome"]["memory_hits"] < 1
    ):
        raise PairIntegrityError("fresh-process Context injection failed")
    observed_ids = sorted(
        {
            memory_id
            for hit in observed_recall.get("hits", [])
            for memory_id in hit.get("metadata", {}).get(
                "rendered_memory_ids",
                [],
            )
        }
    )
    if not observed_ids or not set(observed_ids).issubset(expected_ids):
        raise PairIntegrityError("observed Memory IDs do not match durable truth")
    provenance = _recall_provenance(observed_recall)
    journal = _pico_source_journal(runtime_a)
    learning_journal = _public_journal_state(
        codecairn_cli,
        repository_a,
        journal,
        env,
    )
    if (
        not provenance["source_uris"]
        or provenance["source_cursor"] is None
        or provenance["index_cursor"] is None
        or learning_journal.get("committed_raw_event_index") is None
        or not learning_journal.get("episode_ids")
    ):
        raise PairIntegrityError(
            "installed continuity evidence is missing provenance or cursors",
        )

    repository_b_observation = scratch / "repository-b-recall.json"
    repository_b_result = _worker(
        python,
        worker,
        {
            **base,
            "memory_enabled": True,
            "mode": "evaluate",
            "prompt": (f"Recover {key} from repository Memory and write result.json."),
            "recall_observation": str(repository_b_observation),
            "workspace": str(repository_b),
        },
        scratch / "repository-b",
        env={**env, "PICO_HOME": str(scratch / "pico-home-repository-b")},
    )
    repository_b_recall = _read_json(repository_b_observation) if repository_b_observation.exists() else {"hits": []}
    if (
        not _clean_turn(repository_b_result, expected_backend=True)
        or (repository_b / "result.json").exists()
        or repository_b_result["outcome"]["memory_hits"] != 0
        or repository_b_recall.get("hits")
    ):
        raise PairIntegrityError("repository identity isolation failed")

    memory_off_observation = scratch / "memory-off-recall.json"
    runtime_before_memory_off = _tree_digest(runtime_a)
    memory_off = _worker(
        python,
        worker,
        {
            **base,
            "memory_enabled": False,
            "mode": "evaluate",
            "prompt": (f"Recover {key} from repository Memory and write result.json."),
            "recall_observation": str(memory_off_observation),
            "workspace": str(repository_a),
        },
        scratch / "memory-off",
        env={**env, "PICO_HOME": str(scratch / "pico-home-memory-off")},
    )
    runtime_after_memory_off = _tree_digest(runtime_a)
    if (
        not _clean_turn(memory_off, expected_backend=False)
        or memory_off["memory_backend_build_calls"] != 0
        or memory_off["outcome"]["memory_hits"] != 0
        or memory_off_observation.exists()
        or runtime_after_memory_off != runtime_before_memory_off
    ):
        raise PairIntegrityError("memory-off touched CodeCairn operations")

    replay = _verify_replay_and_prefix(
        codecairn_cli=codecairn_cli,
        repository=repository_a,
        journal=journal,
        env=env,
        expected_ids=expected_ids,
        marker=marker,
    )
    failures = _verify_failure_contracts(
        scratch=scratch,
        python=python,
        worker=worker,
        codecairn_cli=codecairn_cli,
        env=env,
        local_provider=local_provider,
        repository_a=repository_a,
        journal=journal,
        base=base,
    )
    local_skill_query = "persist a recalled repository release fact"
    local_skill_on = _worker(
        python,
        worker,
        {
            **base,
            "conversation_id": "local-skill-codecairn",
            "memory_enabled": True,
            "message_id": "local-skill-codecairn",
            "mode": "evaluate",
            "output_file": "local-skill-codecairn.json",
            "prompt": local_skill_query,
            "recall_observation": str(
                scratch / "local-skill-codecairn-recall.json",
            ),
            "skill_forge_enabled": True,
            "workspace": str(repository_a),
        },
        scratch / "local-skill-codecairn",
        env={
            **env,
            "PICO_HOME": str(scratch / "pico-home-local-skill-codecairn"),
        },
    )
    local_skill_off = _worker(
        python,
        worker,
        {
            **base,
            "conversation_id": "local-skill-memory-off",
            "memory_enabled": False,
            "message_id": "local-skill-memory-off",
            "mode": "evaluate",
            "output_file": "local-skill-memory-off.json",
            "prompt": local_skill_query,
            "recall_observation": str(
                scratch / "local-skill-memory-off-recall.json",
            ),
            "skill_forge_enabled": True,
            "workspace": str(repository_b),
        },
        scratch / "local-skill-memory-off",
        env={
            **env,
            "PICO_HOME": str(scratch / "pico-home-local-skill-memory-off"),
        },
    )
    expected_local_skills = ["local/joint-release"]
    local_skills_same = bool(
        _skill_inventory(repository_a) == _skill_inventory(repository_b)
        and _clean_turn(local_skill_on, expected_backend=True)
        and _clean_turn(local_skill_off, expected_backend=False)
        and local_skill_on["outcome"].get("injected_skill_ids")
        == local_skill_off["outcome"].get("injected_skill_ids")
        == expected_local_skills
    )
    j1 = {
        "backend_module": evaluation["backend_module"],
        "consuming_turn": conversation,
        "expected_memory_ids": expected_ids,
        "fresh_process": True,
        "freshness": sidecar["freshness"],
        "import_cursor": provenance["source_cursor"],
        "index_cursor": provenance["index_cursor"],
        "journal_cursor": learning_journal["committed_raw_event_index"],
        "observed_memory_ids": observed_ids,
        "passed": True,
        "source_uris": provenance["source_uris"],
        "terminal": evaluation["terminal"],
    }
    j2 = {
        "failure_contracts": failures,
        "local_skill_selection": {
            "codecairn": local_skill_on,
            "memory_off": local_skill_off,
        },
        "local_skills_same": local_skills_same,
        "memory_off_backend_module_imported_for_discovery": (memory_off["codecairn_backend_module_loaded"]),
        "memory_off_operation_calls": memory_off["memory_backend_build_calls"],
        "memory_off_runtime_digest": runtime_after_memory_off,
        "passed": bool(local_skills_same and replay["passed"] and failures["passed"]),
        "replay": replay,
        "repository_b_memory_hits": repository_b_result["outcome"]["memory_hits"],
        "repository_leakage_count": 0,
    }
    return {"j1": j1, "j2": j2}


def _verify_replay_and_prefix(
    *,
    codecairn_cli: Path,
    repository: Path,
    journal: Path,
    env: dict[str, str],
    expected_ids: list[str],
    marker: str,
) -> dict[str, object]:
    baseline_state = _public_journal_state(
        codecairn_cli,
        repository,
        journal,
        env,
    )
    baseline_episode_ids = baseline_state.get("episode_ids")
    if not isinstance(baseline_episode_ids, list) or not baseline_episode_ids:
        raise PairIntegrityError(
            "Source Journal baseline has no durable Episode identity",
        )
    baseline_ids = baseline_state["memory_ids"]
    if not set(expected_ids).issubset(baseline_ids):
        raise PairIntegrityError(
            "Source Journal baseline lost the learning Memory identity",
        )
    first = _codecairn_import(
        codecairn_cli,
        repository,
        journal,
        env,
    )
    second = _codecairn_import(
        codecairn_cli,
        repository,
        journal,
        env,
    )
    replay_state = _public_journal_state(
        codecairn_cli,
        repository,
        journal,
        env,
    )
    if (
        first.get("ok") is not True
        or second.get("ok") is not True
        or first.get("created_memory_count") != 0
        or second.get("created_memory_count") != 0
        or replay_state != baseline_state
    ):
        raise PairIntegrityError(
            "Source Journal replay did not preserve Memory identity: "
            + json.dumps(
                {
                    "baseline_ids": baseline_ids,
                    "baseline_state": baseline_state,
                    "first": first,
                    "replay_state": replay_state,
                    "second": second,
                },
                sort_keys=True,
            )
        )
    original = journal.read_bytes()
    try:
        journal.write_bytes(original + b'{"record_type":"batch"')
        tail = _codecairn_import(
            codecairn_cli,
            repository,
            journal,
            env,
            check=False,
        )
    finally:
        journal.write_bytes(original)
    tail_state = _public_journal_state(
        codecairn_cli,
        repository,
        journal,
        env,
    )
    if tail_state != baseline_state:
        raise PairIntegrityError(
            "truncated Source Journal tail changed durable state",
        )
    encoded_marker = marker.encode()
    if encoded_marker not in original:
        raise PairIntegrityError("Source Journal does not contain the task marker")
    conflict_bytes = original.replace(
        encoded_marker,
        b"x" * len(encoded_marker),
        1,
    )
    try:
        journal.write_bytes(conflict_bytes)
        conflict = _codecairn_import(
            codecairn_cli,
            repository,
            journal,
            env,
            check=False,
        )
    finally:
        journal.write_bytes(original)
    conflict_error = conflict.get("error")
    if (
        conflict.get("ok") is not False
        or not isinstance(conflict_error, dict)
        or conflict_error.get("code") != "source_rewritten"
    ):
        raise PairIntegrityError("committed Source Journal prefix conflict did not fail explicitly")
    final_state = _public_journal_state(
        codecairn_cli,
        repository,
        journal,
        env,
    )
    if final_state != baseline_state:
        raise PairIntegrityError(
            "prefix conflict changed durable Source Journal state",
        )
    return {
        "first_created_memory_count": first.get(
            "created_memory_count",
        ),
        "episode_identity_count": len(baseline_episode_ids),
        "memory_identity_count": len(baseline_ids),
        "passed": True,
        "prefix_conflict_code": conflict_error.get("code"),
        "second_created_memory_count": second.get(
            "created_memory_count",
        ),
        "tail_rejected": tail.get("ok") is False,
    }


def _verify_failure_contracts(
    *,
    scratch: Path,
    python: Path,
    worker: Path,
    codecairn_cli: Path,
    env: dict[str, str],
    local_provider: _LocalOpenAIProvider,
    repository_a: Path,
    journal: Path,
    base: dict[str, object],
) -> dict[str, object]:
    failures: dict[str, dict[str, object]] = {}
    missing = scratch / "failure-missing"
    _init_git_repository(missing)
    failures["missing_initialization"] = _worker(
        python,
        worker,
        {
            "worker_mode": "backend_failure",
            "workspace": str(missing),
        },
        scratch / "failure-missing-spec",
        env={**env, "PICO_HOME": str(scratch / "failure-missing-home")},
    )
    mismatch = scratch / "failure-mismatch"
    _init_git_repository(mismatch)
    _init_codecairn(
        codecairn_cli,
        mismatch,
        mismatch / "runtime",
        "joint/failure-mismatch",
        env,
    )
    failures["workspace_mismatch"] = _worker(
        python,
        worker,
        {
            "worker_mode": "backend_failure",
            "workspace": str(mismatch),
        },
        scratch / "failure-mismatch-spec",
        env={**env, "PICO_HOME": str(scratch / "failure-mismatch-home")},
    )

    stage = journal.with_name(f".{journal.stem}.stage.jsonl")
    stage.write_bytes(b'{"record_type":"batch"')
    failures["malformed_journal"] = _worker(
        python,
        worker,
        {
            "worker_mode": "backend_failure",
            "workspace": str(repository_a),
        },
        scratch / "failure-malformed-spec",
        env={**env, "PICO_HOME": str(scratch / "failure-malformed-home")},
    )
    stage.unlink(missing_ok=True)

    invalid_import = scratch / "failure-import.jsonl"
    invalid_import.write_text(
        json.dumps(
            {
                "created_by": "codecairn",
                "provider": "pico",
                "record_type": "header",
                "repo_key": "joint/repository-a",
                "schema": "codecairn.pico.source.invalid",
                "session_id": "invalid-import",
                "source_generation": 1,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    failures["import_failure"] = _codecairn_import(
        codecairn_cli,
        repository_a,
        invalid_import,
        env,
        check=False,
    )

    stop_failure = _worker(
        python,
        worker,
        {
            **base,
            "inject_before_close": "malformed_stage",
            "source_journal": str(journal),
            "memory_enabled": True,
            "mode": "evaluate",
            "prompt": "Inspect Memory and complete a no-op response.",
            "recall_observation": str(scratch / "failure-stop-recall.json"),
            "workspace": str(repository_a),
        },
        scratch / "failure-stop",
        env={**env, "PICO_HOME": str(scratch / "failure-stop-home")},
    )
    failures["backend_stop"] = {
        "error": stop_failure.get("close_error"),
        "phase": "stop",
    }
    stage.unlink(missing_ok=True)

    index_repo = scratch / "failure-index"
    index_runtime = scratch / "failure-index-runtime"
    _init_git_repository(index_repo)
    index_env = {
        **env,
        "CODECAIRN_EMBEDDING_API_KEY": "local-stage-a",
        "CODECAIRN_EMBEDDING_ENDPOINT": local_provider.endpoint,
    }
    _init_codecairn(
        codecairn_cli,
        index_repo,
        index_runtime,
        "joint/failure-index",
        index_env,
        retrieval_profile="dashscope",
    )
    local_provider.fail_embeddings = True
    remember = _run(
        (
            str(codecairn_cli),
            "remember",
            "repository_knowledge",
            "The index failure probe is deterministic.",
            "--subject-key",
            "index-failure-probe",
        ),
        cwd=index_repo,
        env=index_env,
        check=False,
    )
    failures["index_seed"] = {
        "returncode": remember.returncode,
    }
    failures["index_not_ready"] = _worker(
        python,
        worker,
        {
            "worker_mode": "backend_failure",
            "workspace": str(index_repo),
        },
        scratch / "failure-index-spec",
        env={
            **index_env,
            "PICO_HOME": str(scratch / "failure-index-home"),
        },
    )
    local_provider.fail_embeddings = False

    expected_codes = {
        "backend_stop": {
            "pico_journal_invalid",
            "codecairn_stop_failed",
        },
        "index_not_ready": {
            "index_not_ready",
            "codecairn_startup_invalid",
        },
        "import_failure": {"TraceParseError"},
        "malformed_journal": {
            "pico_journal_invalid",
            "codecairn_startup_failed",
        },
        "missing_initialization": {"codecairn_not_initialized"},
        "workspace_mismatch": {"codecairn_repository_mismatch"},
    }
    typed = True
    for name, allowed in expected_codes.items():
        record = failures[name]
        error = record.get("error")
        if not isinstance(error, dict):
            typed = False
            continue
        if error.get("code") not in allowed or not error.get("remediation"):
            typed = False
    return {
        "cases": failures,
        "passed": typed,
        "typed_failures": typed,
    }


class _LocalOpenAIProvider(AbstractContextManager["_LocalOpenAIProvider"]):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.certificate = self.root / "certificate.pem"
        self._key = self.root / "key.pem"
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.semantic_calls = 0
        self.embedding_calls = 0
        self.external_calls = 0
        self.fail_embeddings = False

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise RuntimeError("local provider is not running")
        return f"https://localhost:{self._server.server_port}/v1"

    def __enter__(self) -> _LocalOpenAIProvider:
        openssl = shutil.which("openssl")
        if openssl is None:
            raise PairIntegrityError("openssl is required for the local HTTPS Gate")
        _run(
            (
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(self._key),
                "-out",
                str(self.certificate),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ),
            cwd=self.root,
            env=os.environ.copy(),
        )
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    request = json.loads(raw)
                except json.JSONDecodeError:
                    self.send_error(400)
                    return
                if self.path.endswith("/chat/completions"):
                    owner.semantic_calls += 1
                    content = json.dumps(
                        {"candidates": [], "evolution": []},
                        sort_keys=True,
                    )
                    self._json(
                        {
                            "choices": [{"message": {"content": content, "role": "assistant"}}],
                            "usage": {
                                "completion_tokens": 8,
                                "prompt_tokens": 64,
                                "total_tokens": 72,
                            },
                        }
                    )
                    return
                if self.path.endswith("/embeddings"):
                    owner.embedding_calls += 1
                    if owner.fail_embeddings:
                        self.send_error(503)
                        return
                    values = request.get("input", [])
                    values = [values] if isinstance(values, str) else values
                    dimension = int(request.get("dimensions", 1024))
                    self._json(
                        {
                            "data": [
                                {
                                    "embedding": [0.0] * dimension,
                                    "index": index,
                                }
                                for index, _ in enumerate(values)
                            ],
                            "usage": {
                                "prompt_tokens": sum(len(str(value).split()) for value in values),
                                "total_tokens": sum(len(str(value).split()) for value in values),
                            },
                        }
                    )
                    return
                self.send_error(404)

            def _json(self, value: object) -> None:
                encoded = json.dumps(value, sort_keys=True).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificate, self._key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def receipt(self) -> dict[str, object]:
        return {
            "billable": False,
            "embedding_calls": self.embedding_calls,
            "endpoint_class": "loopback_https",
            "external_calls": self.external_calls,
            "semantic_calls": self.semantic_calls,
        }


def _install_pair(
    root: Path,
    *,
    pico_wheel: Path,
    codecairn_wheel: Path,
) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        raise PairIntegrityError("uv is required for installed verification")
    environment = root / "environment"
    _run(
        (uv, "venv", "--python", "3.12", str(environment)),
        cwd=root,
        env={**os.environ, "PYTHONPATH": ""},
    )
    override = root / "codecairn-override.txt"
    override.write_text(
        f"codecairn @ {codecairn_wheel.resolve().as_uri()}\n",
        encoding="utf-8",
    )
    _run(
        (
            uv,
            "pip",
            "install",
            "--python",
            str(environment / "bin" / "python"),
            "--overrides",
            str(override),
            str(pico_wheel.resolve()),
        ),
        cwd=root,
        env={**os.environ, "PYTHONPATH": ""},
    )
    return environment


def _init_codecairn(
    executable: Path,
    repository: Path,
    runtime_root: Path,
    repo_key: str,
    env: dict[str, str],
    *,
    retrieval_profile: str = "fastembed",
) -> None:
    _run(
        (
            str(executable),
            "init",
            "--root",
            str(runtime_root),
            "--repo-key",
            repo_key,
            "--retrieval-profile",
            retrieval_profile,
            "--semantic-profile",
            "joint-deterministic",
            "--prefetch",
        ),
        cwd=repository,
        env=env,
    )


def _worker(
    python: Path,
    worker: Path,
    spec: dict[str, object],
    root: Path,
    *,
    env: dict[str, str],
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    spec_path = root / "spec.json"
    _write_json(spec_path, spec)
    completed = _run(
        (str(python), "-I", str(worker), str(spec_path)),
        cwd=root,
        env={**env, "PYTHONPATH": ""},
    )
    try:
        value = json.loads(completed.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise PairIntegrityError("installed worker returned invalid JSON") from error
    if not isinstance(value, dict):
        raise PairIntegrityError("installed worker receipt must be an object")
    return value


def _verify_installed_identity(
    identity: dict[str, Any],
    *,
    environment: Path,
    pico_source_root: Path,
    codecairn_source_root: Path,
) -> None:
    expected_entry = [
        "pico.plugins",
        "codecairn",
        "codecairn.integrations.pico",
    ]
    if expected_entry not in identity.get("entry_points", []):
        raise PairIntegrityError("installed CodeCairn entry point is missing")
    site_root = environment.resolve()
    forbidden = (pico_source_root.resolve(), codecairn_source_root.resolve())
    for name in ("pico", "codecairn"):
        record = identity.get(name)
        if not isinstance(record, dict):
            raise PairIntegrityError(f"installed {name} identity is missing")
        location = Path(str(record.get("location", ""))).resolve()
        if not location.is_relative_to(site_root):
            raise PairIntegrityError(f"{name} did not resolve from the installed environment")
        if any(location.is_relative_to(root) for root in forbidden):
            raise PairIntegrityError(f"{name} resolved from a source checkout")
    for item in identity.get("sys_path", []):
        if not item:
            continue
        path = Path(item).resolve()
        if any(path.is_relative_to(root) for root in forbidden):
            raise PairIntegrityError("installed worker sys.path contains a source checkout")


def _clean_turn(value: Mapping[str, Any], *, expected_backend: bool) -> bool:
    expected_module = "codecairn.integrations.pico.backend" if expected_backend else None
    return bool(
        value.get("terminal") == "completed"
        and value.get("backend_module") == expected_module
        and value.get("close_error") is None
        and isinstance(value.get("outcome"), dict)
        and value["outcome"].get("status") == "completed"
    )


def _codecairn_list(
    executable: Path,
    repository: Path,
    env: dict[str, str],
) -> list[dict[str, Any]]:
    value = _command_json((str(executable), "list"), cwd=repository, env=env)
    if not isinstance(value, list):
        raise PairIntegrityError("codecairn list returned an invalid payload")
    return [item for item in value if isinstance(item, dict)]


def _codecairn_import(
    executable: Path,
    repository: Path,
    source: Path,
    env: dict[str, str],
    *,
    check: bool = True,
) -> dict[str, Any]:
    completed = _run(
        (
            str(executable),
            "import",
            str(source),
            "--no-index",
        ),
        cwd=repository,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        error = _typed_codecairn_cli_error(completed)
        if check:
            raise PairIntegrityError(
                f"codecairn import failed: {error['message']}",
            )
        return {
            "error": error,
            "ok": False,
            "returncode": completed.returncode,
        }
    try:
        value = json.loads(completed.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise PairIntegrityError(
            "codecairn import returned invalid JSON",
        ) from error
    if not isinstance(value, dict):
        raise PairIntegrityError(
            "codecairn import receipt must be an object",
        )
    return {
        **value,
        "ok": True,
        "returncode": completed.returncode,
    }


def _typed_codecairn_cli_error(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, str]:
    detail = completed.stderr.strip() or completed.stdout.strip()
    detail = re.sub(r"\x1b\[[0-9;]*m", "", detail)
    match = re.search(
        r"(?:^|\n)(?:codecairn\.memory\.errors\.)?"
        r"(SourceRewritten|TraceParseError):\s*([^\n]+)",
        detail,
    )
    if match is None:
        return {
            "code": "command_failed",
            "message": detail[-1000:],
            "remediation": detail.splitlines()[-1] if detail else "codecairn import failed",
            "type": "CommandFailed",
        }
    error_type, message = match.groups()
    return {
        "code": ("source_rewritten" if error_type == "SourceRewritten" else "TraceParseError"),
        "message": message,
        "remediation": message,
        "type": error_type,
    }


def _pico_source_journal(runtime_root: Path) -> Path:
    journals = list(runtime_root.glob("sources/pico/**/*.jsonl"))
    if len(journals) != 1:
        raise PairIntegrityError(
            "expected exactly one Pico Source Journal",
        )
    return journals[0]


def _public_journal_state(
    executable: Path,
    repository: Path,
    source: Path,
    env: dict[str, str],
) -> dict[str, object]:
    imported = _codecairn_import(
        executable,
        repository,
        source,
        env,
    )
    committed = imported.get("committed_raw_event_index")
    resumed = imported.get("resumed_from_raw_event_index")
    if (
        isinstance(committed, bool)
        or not isinstance(committed, int)
        or isinstance(resumed, bool)
        or not isinstance(resumed, int)
    ):
        raise PairIntegrityError(
            "codecairn import did not expose durable journal cursors",
        )
    memories = _codecairn_list(executable, repository, env)
    return {
        "committed_raw_event_index": committed,
        "episode_ids": sorted(
            {str(memory["episode_id"]) for memory in memories if isinstance(memory.get("episode_id"), str)}
        ),
        "memory_ids": sorted(_memory_ids(memories)),
        "resumed_from_raw_event_index": resumed,
        "source_exists": source.is_file(),
    }


def _memory_ids(memories: list[dict[str, Any]]) -> set[str]:
    return {str(memory["memory_id"]) for memory in memories if isinstance(memory.get("memory_id"), str)}


def _command_json(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
) -> Any:
    completed = _run(command, cwd=cwd, env=env)
    try:
        return json.loads(completed.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise PairIntegrityError(f"command returned invalid JSON: {Path(command[0]).name}") from error


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise PairIntegrityError(f"command failed ({Path(command[0]).name}): {detail[-1000:]}")
    return completed


def _init_git_repository(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(
        ("git", "init", "-q"),
        cwd=path,
        env=os.environ.copy(),
    )


def _seed_local_skill(repository: Path) -> None:
    skill = repository / "skills" / "joint-release" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: joint-release\ndescription: Verify a release fact.\n---\n"
        "Use the repository release fact when it is relevant.\n",
        encoding="utf-8",
    )


def _skill_inventory(repository: Path) -> dict[str, str]:
    root = repository / "skills"
    return {str(path.relative_to(repository)): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file()}


def _tree_digest(root: Path) -> str:
    return _digest_json(
        {str(path.relative_to(root)): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file()}
    )


def _clean_source_commit(
    root: Path,
    *,
    label: str = "Pico",
) -> str:
    status = _run(
        ("git", "status", "--porcelain"),
        cwd=root,
        env=os.environ.copy(),
    ).stdout
    if status:
        raise PairIntegrityError(f"{label} source tree must be clean")
    commit = _run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        env=os.environ.copy(),
    ).stdout.strip()
    if not _COMMIT_RE.fullmatch(commit):
        raise PairIntegrityError(f"{label} source commit is invalid")
    return commit


def _verify_pico_distribution_report(
    path: Path,
    *,
    pico_commit: str,
    pico_wheel_sha256: str,
) -> dict[str, str]:
    report = _read_json(path)
    source = report.get("source")
    artifacts = report.get("artifacts")
    wheel = artifacts.get("wheel") if isinstance(artifacts, dict) else None
    if (
        report.get("schema_version") != 3
        or report.get("status") != "passed"
        or report.get("source_sha") != pico_commit
        or not isinstance(source, dict)
        or source.get("commit") != pico_commit
        or source.get("clean") is not True
        or source.get("unchanged_during_verification") is not True
        or not isinstance(wheel, dict)
        or wheel.get("sha256") != pico_wheel_sha256
    ):
        raise PairIntegrityError(
            "current Pico wheel is not bound to the clean source commit by V-P0",
        )
    source_manifest = source.get("source_manifest_sha256")
    if not isinstance(source_manifest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_manifest):
        raise PairIntegrityError(
            "Pico distribution report has no source manifest digest",
        )
    return {
        "source_manifest_sha256": source_manifest,
    }


def _recall_provenance(
    observation: Mapping[str, Any],
) -> dict[str, object]:
    hits = observation.get("hits")
    metadata = (
        [hit.get("metadata") for hit in hits if isinstance(hit, dict) and isinstance(hit.get("metadata"), dict)]
        if isinstance(hits, list)
        else []
    )
    source_uris = sorted(
        {uri for item in metadata for uri in item.get("source_uris", []) if isinstance(uri, str) and uri}
    )
    source_cursors = {item.get("source_cursor") for item in metadata if item.get("source_cursor") is not None}
    index_cursors = {item.get("index_cursor") for item in metadata if item.get("index_cursor") is not None}
    return {
        "index_cursor": (next(iter(index_cursors)) if len(index_cursors) == 1 else None),
        "source_cursor": (next(iter(source_cursors)) if len(source_cursors) == 1 else None),
        "source_uris": source_uris,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PairIntegrityError(f"cannot read JSON artifact {path.name}") from error
    if not isinstance(value, dict):
        raise PairIntegrityError(f"JSON artifact {path.name} must be an object")
    return value


def _digest_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _verify_plugin_inventory(data: dict[str, Any], wheel: Path) -> None:
    inventory = _mapping(data, "plugin_inventory")
    entry_points = inventory.get("entry_points")
    if entry_points != [_EXPECTED_CONTRACT["entry_point"]]:
        raise PairIntegrityError("CodeCairn Plugin entry-point inventory mismatch")
    plugins = inventory.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1:
        raise PairIntegrityError("CodeCairn Plugin inventory must contain one Plugin")
    plugin = plugins[0]
    if not isinstance(plugin, dict) or (
        plugin.get("id") != _EXPECTED_CONTRACT["plugin_id"]
        or plugin.get("memory_backends") != [_EXPECTED_CONTRACT["memory_backend"]]
        or plugin.get("tools") != []
    ):
        raise PairIntegrityError("CodeCairn Plugin contribution inventory mismatch")
    if _wheel_entry_points(wheel).get(("pico.plugins", "codecairn")) != ("codecairn.integrations.pico"):
        raise PairIntegrityError("CodeCairn wheel entry point is incompatible")


def _load_handoff(path: Path, *, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PairIntegrityError(f"cannot read handoff {path.name}") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("kind") != kind:
        raise PairIntegrityError(f"handoff {path.name} has an unknown schema")
    return value


def _wheel_metadata(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(candidates) != 1:
                raise PairIntegrityError(f"wheel {path.name} has invalid distribution metadata")
            metadata = Parser().parsestr(archive.read(candidates[0]).decode("utf-8"))
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise PairIntegrityError(f"cannot inspect wheel {path.name}") from error
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not name or not version:
        raise PairIntegrityError(f"wheel {path.name} has incomplete metadata")
    return name, version


def _wheel_entry_points(path: Path) -> dict[tuple[str, str], str]:
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = [name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")]
            if len(candidates) != 1:
                raise PairIntegrityError(f"wheel {path.name} has invalid entry-point metadata")
            lines = archive.read(candidates[0]).decode("utf-8").splitlines()
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise PairIntegrityError(f"cannot inspect wheel {path.name}") from error
    group = ""
    entries: dict[tuple[str, str], str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            group = stripped[1:-1]
            continue
        if "=" not in stripped:
            raise PairIntegrityError(f"wheel {path.name} has malformed entry-point metadata")
        name, value = (part.strip() for part in stripped.split("=", 1))
        entries[(group, name)] = value
    return entries


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    candidate = value.get(key)
    if not isinstance(candidate, dict):
        raise PairIntegrityError(f"handoff field {key} must be an object")
    return candidate


def _commit(value: object, label: str) -> str:
    text = _string(value, label)
    if not _COMMIT_RE.fullmatch(text):
        raise PairIntegrityError(f"{label} must be a 40-character SHA")
    return text


def _digest(value: object, label: str) -> str:
    text = _string(value, label)
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise PairIntegrityError(f"{label} must be a SHA-256 digest")
    return text


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PairIntegrityError(f"{label} must be a non-empty string")
    return value


def _sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as error:
        raise PairIntegrityError(f"cannot hash {path.name}") from error


__all__ = [
    "PairAudit",
    "PairIntegrityError",
    "audit_pair_inputs",
]
