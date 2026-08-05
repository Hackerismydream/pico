from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from .artifacts import ArtifactStore
from .budget import BudgetGuardedProvider
from .campaign import (
    CampaignError,
    CampaignMode,
    CampaignOutcome,
    DeterministicGateResult,
    ResolvedProvider,
    default_campaign_services,
    load_campaign_suite,
    run_campaign,
)
from .canonical import canonical_digest, to_primitive
from .codecairn_continuity import PairIntegrityError, _read_json, _sha256
from .packs.codecairn_memory import (
    ProductionCodeCairnMemoryRunner,
    create_codecairn_memory_calibration_pack,
    create_codecairn_memory_pack,
)
from .registry import PackRegistry
from .schema import ExperimentRef

DEFAULT_CODECAIRN_SUITE_PATH = Path(__file__).resolve().parent / "suites" / "codecairn_memory_effect.yaml"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


async def run_codecairn_campaign(
    mode: CampaignMode,
    *,
    output_root: Path,
    suite_path: Path = DEFAULT_CODECAIRN_SUITE_PATH,
) -> CampaignOutcome:
    suite = load_campaign_suite(suite_path)
    paths = _campaign_paths()
    runner_cache: dict[
        str,
        ProductionCodeCairnMemoryRunner,
    ] = {}
    defaults = default_campaign_services()

    async def deterministic(
        _output_root: Path,
    ) -> DeterministicGateResult:
        summary = _read_json(paths["continuity_summary"])
        manifest = _read_json(paths["pair_manifest"])
        passed = bool(
            summary.get("passed") is True
            and summary.get("paid_external_calls") == 0
            and summary.get("pair_manifest_sha256") == _sha256(paths["pair_manifest"])
            and manifest.get("schema") == "pico.codecairn.pair-manifest.v1"
        )
        return DeterministicGateResult(
            passed=passed,
            details={
                "continuity_summary_sha256": _sha256(
                    paths["continuity_summary"],
                ),
                "pair_manifest_sha256": _sha256(
                    paths["pair_manifest"],
                ),
                "stage": "installed-codecairn-continuity",
            },
            evidence_path=str(
                paths["continuity_summary"],
            ),
            evidence_digest=_sha256(
                paths["continuity_summary"],
            ),
        )

    def build_registry(
        selected_mode: CampaignMode,
        resolved: ResolvedProvider,
    ) -> PackRegistry:
        if (
            resolved.config is None
            or resolved.pico_config is None
            or resolved.budget_ledger is None
            or not isinstance(
                resolved.provider,
                BudgetGuardedProvider,
            )
            or resolved.provider.ledger is not resolved.budget_ledger
        ):
            raise CampaignError(
                "CodeCairn campaign requires the shared guarded Provider ledger",
            )
        runner = runner_cache.get("installed_pair")
        if runner is None:
            try:
                runner = ProductionCodeCairnMemoryRunner(
                    config=resolved.config,
                    pico_config=resolved.pico_config,
                    provider=resolved.provider,
                    pico_wheel=paths["pico_wheel"],
                    codecairn_wheel=paths["codecairn_wheel"],
                    pair_manifest=paths["pair_manifest"],
                    continuity_summary=paths["continuity_summary"],
                    benchmark_source_root=_REPOSITORY_ROOT,
                )
            except PairIntegrityError as error:
                raise CampaignError(
                    f"CodeCairn paid preflight failed before Trial execution: {error}",
                ) from error
            runner_cache["installed_pair"] = runner
        registry = PackRegistry()
        registry.register(
            create_codecairn_memory_calibration_pack(
                runner,
            )
            if selected_mode is CampaignMode.CALIBRATION
            else create_codecairn_memory_pack(runner)
        )
        return registry

    services = replace(
        defaults,
        run_deterministic=deterministic,
        build_registry=build_registry,
    )
    outcome = await run_campaign(
        mode,
        output_root=output_root,
        suite=suite,
        services=services,
    )
    if mode is CampaignMode.SHIP:
        _write_completion_handoff(
            outcome,
            paths=paths,
        )
    return outcome


def _campaign_paths() -> dict[str, Path]:
    names = {
        "codecairn_wheel": "PICO_CODECAIRN_WHEEL",
        "continuity_summary": ("PICO_CODECAIRN_CONTINUITY_SUMMARY"),
        "pair_manifest": "PICO_CODECAIRN_PAIR_MANIFEST",
        "pico_wheel": "PICO_CODECAIRN_PICO_WHEEL",
    }
    paths: dict[str, Path] = {}
    for key, environment_name in names.items():
        value = os.environ.get(environment_name)
        if not value:
            raise CampaignError(
                f"{environment_name} is required",
            )
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise CampaignError(
                f"{environment_name} does not name a file",
            )
        paths[key] = path
    identity = canonical_digest(
        {
            key: {
                "path_name": path.name,
                "sha256": _sha256(path),
            }
            for key, path in sorted(paths.items())
        }
    )
    if not identity:
        raise CampaignError(
            "CodeCairn campaign pair identity is empty",
        )
    manifest = _read_json(paths["pair_manifest"])
    summary = _read_json(paths["continuity_summary"])
    audit = manifest.get("audit")
    current_pico = audit.get("current_pico") if isinstance(audit, dict) else None
    codecairn = audit.get("codecairn") if isinstance(audit, dict) else None
    if (
        manifest.get("schema") != "pico.codecairn.pair-manifest.v1"
        or summary.get("pair_manifest_sha256") != _sha256(paths["pair_manifest"])
        or not isinstance(current_pico, dict)
        or current_pico.get("commit") != _current_pico_commit()
        or current_pico.get("wheel_sha256") != _sha256(paths["pico_wheel"])
        or not isinstance(codecairn, dict)
        or codecairn.get("wheel_sha256") != _sha256(paths["codecairn_wheel"])
    ):
        raise CampaignError(
            "CodeCairn campaign inputs do not match the frozen Stage A pair",
        )
    return paths


def _current_pico_commit() -> str:
    git = shutil.which("git")
    if git is None:
        raise CampaignError(
            "cannot bind CodeCairn campaign inputs without git",
        )
    completed = subprocess.run(
        (git, "rev-parse", "--verify", "HEAD"),
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise CampaignError(
            "cannot bind CodeCairn campaign inputs to the current Pico commit",
        )
    return value


def _write_completion_handoff(
    outcome: CampaignOutcome,
    *,
    paths: dict[str, Path],
) -> Path:
    if not outcome.campaign_artifact_path or not outcome.reports:
        raise CampaignError(
            "completed CodeCairn Ship has no aggregate campaign artifact",
        )
    campaign_artifact = Path(
        outcome.campaign_artifact_path,
    ).resolve()
    if not campaign_artifact.is_file():
        raise CampaignError(
            "completed CodeCairn Ship campaign artifact is missing",
        )
    pair_manifest = _read_json(paths["pair_manifest"])
    continuity = _read_json(paths["continuity_summary"])
    audit = pair_manifest.get("audit")
    if not isinstance(audit, dict):
        raise CampaignError(
            "CodeCairn Pair Manifest audit is missing",
        )
    experiments = []
    for ref, report in zip(
        outcome.experiments,
        outcome.reports,
        strict=True,
    ):
        summary = ref.root / "summary.json"
        cv_metrics = ref.root / "cv-metrics.json"
        if not summary.is_file() or not cv_metrics.is_file():
            raise CampaignError(
                "CodeCairn experiment report artifacts are incomplete",
            )
        experiments.append(
            {
                "cv_metrics_sha256": _sha256(cv_metrics),
                "experiment_id": ref.experiment_id,
                "measurement_valid": bool(
                    report.measurement_valid,
                ),
                "positive_claim_eligible": bool(
                    getattr(
                        report,
                        "positive_claim_eligible",
                        False,
                    )
                ),
                "report_digest": str(
                    getattr(report, "report_digest", ""),
                ),
                "ship_complete": bool(report.ship_complete),
                "summary_sha256": _sha256(summary),
            }
        )
    formal = outcome.reports[-1]
    snapshot = outcome.budget_snapshot
    budget = (
        {
            "accounting_complete": snapshot.accounting_complete,
            "additional_request_attempt_ceiling": (snapshot.additional_request_attempt_ceiling),
            "additional_request_attempts": (snapshot.additional_request_attempts),
            "approval_digest": snapshot.approval_digest,
            "external_service_reserve_cny": (snapshot.external_service_reserve_cny),
            "hard_cap_cny": snapshot.hard_cap_cny,
            "high_water_digest": snapshot.high_water_digest,
            "ledger_digest": snapshot.ledger_digest,
            "provider_charged_cny": (snapshot.provider_charged_cny),
            "request_attempts": snapshot.request_attempts,
            "total_committed_cny": snapshot.total_committed_cny,
        }
        if snapshot is not None
        else None
    )
    payload = {
        "schema_version": 1,
        "kind": "codecairn.pico.joint-evidence.handoff",
        "pico": audit.get("current_pico"),
        "codecairn": audit.get("codecairn"),
        "deterministic": {
            "continuity_summary_sha256": _sha256(
                paths["continuity_summary"],
            ),
            "j1_passed": bool(
                continuity.get("j1", {}).get("passed") if isinstance(continuity.get("j1"), dict) else False
            ),
            "j2_passed": bool(
                continuity.get("j2", {}).get("passed") if isinstance(continuity.get("j2"), dict) else False
            ),
            "paid_external_calls": continuity.get(
                "paid_external_calls",
            ),
            "pair_manifest_sha256": _sha256(
                paths["pair_manifest"],
            ),
            "passed": continuity.get("passed") is True,
        },
        "campaign": {
            "artifact_sha256": _sha256(campaign_artifact),
            "experiments": experiments,
            "mode": outcome.mode.value,
            "preflight": to_primitive(outcome.preflight),
        },
        "budget": budget,
        "result": {
            "measurement_valid": bool(
                formal.measurement_valid,
            ),
            "positive_claim_eligible": bool(
                getattr(
                    formal,
                    "positive_claim_eligible",
                    False,
                )
            ),
            "ship_complete": bool(formal.ship_complete),
        },
    }
    payload["aggregate_digest"] = canonical_digest(payload)
    handoff = campaign_artifact.with_name(
        "codecairn-v02-003-handoff.json",
    )
    ArtifactStore(
        ExperimentRef(
            experiment_id=str(payload["aggregate_digest"]),
            root=handoff.parent,
        )
    ).append_immutable(handoff, payload)
    return handoff


__all__ = [
    "DEFAULT_CODECAIRN_SUITE_PATH",
    "run_codecairn_campaign",
]
