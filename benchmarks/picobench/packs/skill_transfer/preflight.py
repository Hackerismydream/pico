from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from benchmarks.picobench.budget import BudgetGuardedProvider, ProviderBudgetConfig, ProviderBudgetLedger
from pico.providers.base import LLMProvider, LLMResponse

from .campaign import CampaignConfig, corpus_split_digests, load_corpus
from .runner import InstalledSkillTransferExecutor


class _FixtureSkillProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key="fixture")

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    ) -> LLMResponse:
        del tools, model, max_tokens, temperature, reasoning_effort, tool_choice
        request = json.loads(messages[-1]["content"])
        ability = str(request["ability_fingerprint"])
        content = {
            "name": ability,
            "description": ability,
            "applicability": [ability],
            "procedure": ["Apply the procedure supported by the three verified learning Experiences."],
            "verification": ["Run the task-specific independent verifier before claiming success."],
            "failure_avoidance": ["Do not claim success when verification fails."],
        }
        return LLMResponse(
            content=json.dumps(content, sort_keys=True),
            finish_reason="stop",
            usage={"prompt_tokens": 64, "completion_tokens": 48, "total_tokens": 112},
        )

    def get_default_model(self) -> str:
        return "skill-transfer/fixture"


def run_preflight(config: CampaignConfig) -> dict[str, Any]:
    corpus = load_corpus(config.corpus_path)
    with tempfile.TemporaryDirectory(prefix="skill-transfer-preflight-") as temporary:
        root = Path(temporary)
        budget_config = ProviderBudgetConfig(
            hard_cap_cny=1.0,
            external_service_reserve_cny=0.0,
            max_total_request_attempts=12,
            max_input_tokens_per_call=config.max_input_tokens_per_call,
            max_output_tokens_per_call=config.max_output_tokens_per_call,
            input_cache_miss_usd_per_million=config.input_cache_miss_usd_per_million,
            output_usd_per_million=config.output_usd_per_million,
            conservative_usd_to_cny_multiplier=config.conservative_usd_to_cny_multiplier,
        )
        ledger = ProviderBudgetLedger(root / "provider-budget.jsonl", budget_config)
        provider = BudgetGuardedProvider(_FixtureSkillProvider(), ledger=ledger)
        with InstalledSkillTransferExecutor(
            config,
            provider_api_key="fixture",
            provider_api_base=None,
            skill_provider_override=provider,
        ) as executor:
            executor.configure_budget(ledger.path, budget_config)
            candidate = executor.prepare_candidates(corpus, snapshot_root=root / "candidate-runtimes")
            negatives = executor.hard_negatives(corpus)
            identity = executor.identity
        snapshot = ledger.snapshot()
        expected_learning = corpus_split_digests(corpus)["learning"]
        if candidate.get("candidate_input_digest") != expected_learning:
            raise RuntimeError("preflight candidate input digest mismatch")
        if len(candidate.get("active_revisions", {})) != 6:
            raise RuntimeError("preflight did not create six active Skill revisions")
        expected_admissions = {
            item.instance_id: [candidate["active_revisions"][ability.ability_id]]
            for ability in corpus.abilities
            for item in ability.held_out
        }
        if candidate.get("held_out_admission_precheck") != expected_admissions:
            missing = sorted(
                task_id
                for task_id, expected in expected_admissions.items()
                if candidate.get("held_out_admission_precheck", {}).get(task_id) != expected
            )
            raise RuntimeError(f"preflight held-out admission failed: {missing}")
        if len(negatives) != 24 or any(item.recalled_revision_ids for item in negatives):
            admitted = {
                item.instance_id: list(item.recalled_revision_ids) for item in negatives if item.recalled_revision_ids
            }
            raise RuntimeError(
                f"preflight hard-negative admission failed: count={len(negatives)} admitted={json.dumps(admitted, sort_keys=True)}"
            )
        if snapshot.request_attempts != 6 or not snapshot.accounting_complete:
            raise RuntimeError("preflight Provider accounting is incomplete")
        return {
            "schema": "pico.picobench.skill-transfer.preflight.v1",
            "passed": True,
            "active_revisions": len(candidate["active_revisions"]),
            "held_out_admissions": len(expected_admissions),
            "hard_negatives": len(negatives),
            "incorrect_skill_admissions": sum(bool(item.recalled_revision_ids) for item in negatives),
            "provider_request_attempts": snapshot.request_attempts,
            "installed_identity": identity,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the credential-free installed skill_transfer_v1 preflight")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pico-wheel", type=Path, required=True)
    parser.add_argument("--myna-wheel", type=Path, required=True)
    parser.add_argument("--pico-commit", required=True)
    parser.add_argument("--myna-commit", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = CampaignConfig(
        corpus_path=args.corpus,
        output_root=args.output_root,
        pico_wheel=args.pico_wheel,
        myna_wheel=args.myna_wheel,
        pico_commit=args.pico_commit,
        myna_commit=args.myna_commit,
    )
    print(json.dumps(run_preflight(config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
