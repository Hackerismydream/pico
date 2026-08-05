from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .budget import BudgetGuardedProvider
from .campaign import (
    CampaignError,
    CampaignMode,
    CampaignOutcome,
    CampaignSuite,
    DeterministicGateResult,
    ResolvedProvider,
    default_campaign_services,
    estimate_worst_case_cost,
    load_campaign_suite,
    run_campaign,
)
from .canonical import canonical_digest, to_primitive
from .codecairn_continuity import (
    PairIntegrityError,
    _command_json,
    _init_git_repository,
    _install_pair,
    _read_json,
    _sha256,
    _worker,
)
from .packs.codecairn_memory.production import (
    _minimal_environment,
)
from .packs.codecairn_task_effect import (
    ProductionTaskEffectRunner,
    create_calibration_pack,
    create_formal_pack,
)
from .registry import PackRegistry

DEFAULT_TASK_EFFECT_SUITE_PATH = Path(__file__).resolve().parent / "suites" / "codecairn_task_effect_v2.yaml"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_STAGE_C_SCHEMA = "pico.picobench.codecairn-task-effect-stage-c.v1"
_AUTHORIZATION_SCHEMA = "pico.picobench.codecairn-task-effect-authorization.v1"


async def run_task_effect_campaign(
    mode: CampaignMode,
    *,
    output_root: Path,
    suite_path: Path = DEFAULT_TASK_EFFECT_SUITE_PATH,
) -> CampaignOutcome:
    suite = load_campaign_suite(suite_path)
    paths = _campaign_paths(suite)
    runner_cache: dict[str, ProductionTaskEffectRunner] = {}
    defaults = default_campaign_services()

    async def deterministic(
        _output_root: Path,
    ) -> DeterministicGateResult:
        summary = _read_json(paths["stage_c_summary"])
        passed = bool(
            summary.get("schema") == _STAGE_C_SCHEMA
            and summary.get("passed") is True
            and summary.get("paid_external_calls") == 0
            and summary.get("pico", {}).get("wheel_sha256") == _sha256(paths["pico_wheel"])
            and summary.get("codecairn", {}).get("wheel_sha256") == _sha256(paths["codecairn_wheel"])
        )
        return DeterministicGateResult(
            passed=passed,
            details={
                "stage": "task-effect-v2-installed-pair",
                "stage_c_summary_sha256": _sha256(
                    paths["stage_c_summary"],
                ),
            },
            evidence_path=str(paths["stage_c_summary"]),
            evidence_digest=_sha256(
                paths["stage_c_summary"],
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
                "task-effect campaign requires the shared guarded Provider ledger",
            )
        runner = runner_cache.get("installed_pair")
        if runner is None:
            try:
                runner = ProductionTaskEffectRunner(
                    config=resolved.config,
                    pico_config=resolved.pico_config,
                    provider=resolved.provider,
                    pico_wheel=paths["pico_wheel"],
                    codecairn_wheel=paths["codecairn_wheel"],
                    stage_c_summary=paths["stage_c_summary"],
                    benchmark_source_root=(_REPOSITORY_ROOT),
                )
            except (
                PairIntegrityError,
                ValueError,
            ) as error:
                raise CampaignError(
                    f"task-effect installed-pair preflight failed: {error}",
                ) from error
            runner_cache["installed_pair"] = runner
        registry = PackRegistry()
        registry.register(
            create_calibration_pack(runner) if selected_mode is CampaignMode.CALIBRATION else create_formal_pack(runner)
        )
        return registry

    services = replace(
        defaults,
        run_deterministic=deterministic,
        build_registry=build_registry,
    )
    return await run_campaign(
        mode,
        output_root=output_root,
        suite=suite,
        services=services,
    )


def freeze_stage_c(
    *,
    pico_wheel: Path,
    codecairn_wheel: Path,
    codecairn_commit: str,
    output: Path,
) -> Path:
    pico_wheel = Path(pico_wheel).resolve()
    codecairn_wheel = Path(codecairn_wheel).resolve()
    output = Path(output).resolve()
    if len(codecairn_commit) != 40 or any(character not in "0123456789abcdef" for character in codecairn_commit):
        raise CampaignError(
            "CodeCairn commit must be a lowercase 40-character SHA",
        )
    if not pico_wheel.is_file() or not codecairn_wheel.is_file():
        raise CampaignError(
            "Stage C requires both frozen wheels",
        )
    pico_commit = _current_pico_commit()
    if not _worktree_clean():
        raise CampaignError(
            "Stage C requires a clean Pico worktree",
        )
    with tempfile.TemporaryDirectory(
        prefix="picobench-task-effect-stage-c-",
    ) as temporary:
        root = Path(temporary)
        environment = _install_pair(
            root,
            pico_wheel=pico_wheel,
            codecairn_wheel=codecairn_wheel,
        )
        worker = root / "codecairn_installed_worker.py"
        shutil.copy2(
            _REPOSITORY_ROOT / "benchmarks" / "picobench" / "codecairn_installed_worker.py",
            worker,
        )
        identity = _worker(
            environment / "bin" / "python",
            worker,
            {"worker_mode": "identity"},
            root / "identity",
            env=_minimal_environment(
                root / "identity-home",
                {
                    "PICO_HOME": str(
                        root / "identity-pico-home",
                    )
                },
            ),
        )
        isolation = _installed_identity_isolated(
            identity,
            environment,
        )
        local_retrieval = _local_retrieval_gate(
            environment / "bin" / "codecairn",
            root / "local-retrieval",
        )
    payload: dict[str, Any] = {
        "schema": _STAGE_C_SCHEMA,
        "pico": {
            "commit": pico_commit,
            "wheel_sha256": _sha256(pico_wheel),
        },
        "codecairn": {
            "commit": codecairn_commit,
            "wheel_sha256": _sha256(codecairn_wheel),
        },
        "gates": {
            "installed_identity_digest": canonical_digest(
                identity,
            ),
            "installed_source_isolation": isolation,
            "local_retrieval": local_retrieval,
            "task_contract": ("make picobench-codecairn-task-effect-smoke"),
        },
        "paid_external_calls": 0,
        "passed": bool(isolation and local_retrieval.get("passed") is True),
    }
    payload["stage_c_digest"] = canonical_digest(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8") as handle:
            json.dump(
                to_primitive(payload),
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
    except FileExistsError as error:
        raise CampaignError(
            "Stage C output already exists",
        ) from error
    return output


def _campaign_paths(
    suite: CampaignSuite,
) -> dict[str, Path]:
    names = {
        "pico_wheel": "PICO_TASK_EFFECT_PICO_WHEEL",
        "codecairn_wheel": ("PICO_TASK_EFFECT_CODECAIRN_WHEEL"),
        "stage_c_summary": ("PICO_TASK_EFFECT_STAGE_C_SUMMARY"),
        "authorization": ("PICO_TASK_EFFECT_AUTHORIZATION"),
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
    summary = _read_json(paths["stage_c_summary"])
    authorization = _read_json(paths["authorization"])
    authorization_payload = {
        "schema": authorization.get("schema"),
        "issue": authorization.get("issue"),
        "approved": authorization.get("approved"),
        "stage_c_summary_sha256": authorization.get("stage_c_summary_sha256"),
        "suite_digest": authorization.get("suite_digest"),
        "provider_name": authorization.get("provider_name"),
        "model": authorization.get("model"),
        "warning_cny": authorization.get("warning_cny"),
        "hard_cap_cny": authorization.get("hard_cap_cny"),
    }
    if (
        summary.get("schema") != _STAGE_C_SCHEMA
        or summary.get("passed") is not True
        or summary.get("paid_external_calls") != 0
        or summary.get("pico", {}).get("commit") != _current_pico_commit()
        or summary.get("pico", {}).get("wheel_sha256") != _sha256(paths["pico_wheel"])
        or summary.get("codecairn", {}).get("wheel_sha256") != _sha256(paths["codecairn_wheel"])
        or authorization_payload["schema"] != _AUTHORIZATION_SCHEMA
        or authorization_payload["issue"] != 79
        or authorization_payload["approved"] is not True
        or authorization_payload["stage_c_summary_sha256"] != _sha256(paths["stage_c_summary"])
        or authorization_payload["suite_digest"] != canonical_digest(suite)
        or authorization_payload["provider_name"] != suite.provider.name
        or authorization_payload["model"] != suite.provider.model
        or authorization_payload["warning_cny"] != suite.budget.warning_cny
        or authorization_payload["hard_cap_cny"] != suite.budget.hard_cap_cny
        or authorization.get("authorization_digest") != canonical_digest(authorization_payload)
    ):
        raise CampaignError(
            "task-effect campaign inputs do not match Stage C and paid authority",
        )
    return paths


def _installed_identity_isolated(
    identity: Mapping[str, Any],
    environment: Path,
) -> bool:
    pico = identity.get("pico")
    codecairn = identity.get("codecairn")
    sys_path = identity.get("sys_path")
    if not isinstance(pico, Mapping) or not isinstance(codecairn, Mapping) or not isinstance(sys_path, list):
        return False
    environment = environment.resolve()
    locations = (
        Path(str(pico.get("location", ""))).resolve(),
        Path(str(codecairn.get("location", ""))).resolve(),
    )
    forbidden = {
        _REPOSITORY_ROOT.resolve(),
        Path("/Users/martinlos/code/CodeCairn").resolve(),
    }
    return bool(
        all(location.is_relative_to(environment) for location in locations)
        and not any(Path(str(entry)).resolve() in forbidden for entry in sys_path if entry)
    )


def _local_retrieval_gate(
    codecairn: Path,
    root: Path,
) -> dict[str, Any]:
    repository = root / "repository"
    runtime = root / "runtime"
    _init_git_repository(repository)
    environment = _minimal_environment(
        root / "home",
    )
    initialized = _command_json(
        (
            str(codecairn),
            "init",
            "--root",
            str(runtime),
            "--repo-key",
            "picobench/task-effect-stage-c",
            "--retrieval-profile",
            "fastembed",
            "--prefetch",
        ),
        cwd=repository,
        env=environment,
    )
    remembered = _command_json(
        (
            str(codecairn),
            "remember",
            "repository_knowledge",
            "The Stage C verification marker is cobalt.",
            "--title",
            "Stage C marker",
            "--subject-key",
            "stage_c_marker",
            "--repo-key",
            "picobench/task-effect-stage-c",
            "--root",
            str(runtime),
        ),
        cwd=repository,
        env=environment,
    )
    recalled = _command_json(
        (
            str(codecairn),
            "recall",
            "Which marker belongs to Stage C verification?",
            "--repo-key",
            "picobench/task-effect-stage-c",
            "--root",
            str(runtime),
            "--limit",
            "5",
            "--format",
            "json",
        ),
        cwd=repository,
        env=environment,
    )
    memory_id = remembered.get("memory_id") if isinstance(remembered, Mapping) else None
    sidecar = recalled.get("sidecar") if isinstance(recalled, Mapping) else None
    trace = sidecar.get("context_trace") if isinstance(sidecar, Mapping) else None
    rendered = trace.get("rendered_memory_ids") if isinstance(trace, Mapping) else None
    provider_state = initialized.get("provider_state") if isinstance(initialized, Mapping) else None
    passed = bool(
        isinstance(provider_state, Mapping)
        and provider_state.get("retrieval") == "fastembed"
        and isinstance(memory_id, str)
        and isinstance(rendered, list)
        and memory_id in rendered
    )
    return {
        "memory_identity_present": (isinstance(memory_id, str)),
        "passed": passed,
        "retrieval_profile": (provider_state.get("retrieval") if isinstance(provider_state, Mapping) else None),
    }


def _current_pico_commit() -> str:
    git = shutil.which("git")
    if git is None:
        raise CampaignError("git is required")
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
            "cannot bind campaign to the current Pico commit",
        )
    return value


def _worktree_clean() -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    completed = subprocess.run(
        (git, "status", "--porcelain"),
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0 and not completed.stdout.strip()


def _print_estimate() -> None:
    suite = load_campaign_suite(
        DEFAULT_TASK_EFFECT_SUITE_PATH,
    )
    estimate = estimate_worst_case_cost(
        suite,
        modes=(
            CampaignMode.CALIBRATION,
            CampaignMode.FORMAL,
        ),
    )
    print(
        json.dumps(
            to_primitive(estimate),
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Run the PicoBench task-effect v2 installed campaign."),
    )
    parser.add_argument(
        "action",
        choices=(
            "stage-c",
            "estimate",
            "calibration",
            "formal",
            "ship",
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=(Path(".pico") / "evidence" / "picobench-codecairn-v2"),
    )
    parser.add_argument("--pico-wheel", type=Path)
    parser.add_argument("--codecairn-wheel", type=Path)
    parser.add_argument("--codecairn-commit")
    parser.add_argument("--stage-c-output", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "stage-c":
            if (
                args.pico_wheel is None
                or args.codecairn_wheel is None
                or args.codecairn_commit is None
                or args.stage_c_output is None
            ):
                raise CampaignError(
                    "stage-c requires both wheels, the CodeCairn commit, and an output path",
                )
            path = freeze_stage_c(
                pico_wheel=args.pico_wheel,
                codecairn_wheel=args.codecairn_wheel,
                codecairn_commit=args.codecairn_commit,
                output=args.stage_c_output,
            )
            print(path)
            return 0
        if args.action == "estimate":
            _print_estimate()
            return 0
        outcome = asyncio.run(
            run_task_effect_campaign(
                CampaignMode(args.action),
                output_root=args.output_root,
            )
        )
    except (
        CampaignError,
        PairIntegrityError,
    ) as error:
        parser.exit(
            2,
            f"PicoBench aborted: {error}\n",
        )
    print(
        json.dumps(
            to_primitive(outcome),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_TASK_EFFECT_SUITE_PATH",
    "freeze_stage_c",
    "run_task_effect_campaign",
]
