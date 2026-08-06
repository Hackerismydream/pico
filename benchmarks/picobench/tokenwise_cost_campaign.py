from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from benchmarks.picobench.packs.tokenwise_cost.live import CampaignConfig, CampaignError, load_task_corpus
from benchmarks.picobench.packs.tokenwise_cost.runner import (
    load_deepseek_key,
    run_cache_preflight,
    run_formal_campaign,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_PATH = _REPOSITORY_ROOT / "benchmarks" / "picobench" / "tasks" / "tokenwise_cost" / "formal.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the TokenWise live cost campaign.")
    parser.add_argument("--mode", choices=("preflight", "formal"), default="preflight")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_REPOSITORY_ROOT / ".pico" / "evidence" / "tokenwise-cost",
    )
    parser.add_argument("--execute-paid-campaign", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid_campaign:
        parser.error("--execute-paid-campaign is required because both modes call a paid Provider")

    try:
        result = asyncio.run(_run(args.mode, args.output_root))
    except CampaignError as exc:
        parser.exit(2, f"TokenWise campaign aborted: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


async def _run(mode: str, output_root: Path) -> dict:
    config = CampaignConfig(output_root=output_root)
    api_key = load_deepseek_key()
    corpus = load_task_corpus(_CORPUS_PATH)
    if mode == "preflight":
        return await run_cache_preflight(api_key=api_key, config=config)
    preflight_path = output_root / "preflight.json"
    if not preflight_path.is_file():
        raise CampaignError("run the passing preflight before the formal campaign")
    try:
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError("preflight artifact is unreadable") from exc
    git = shutil.which("git")
    if git is None:
        raise CampaignError("git is required to freeze the Pico commit")
    commit = subprocess.run(
        [git, "rev-parse", "HEAD"],
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return await run_formal_campaign(
        config=config,
        corpus=corpus,
        api_key=api_key,
        pico_commit=commit,
        preflight_report=preflight,
    )


if __name__ == "__main__":
    raise SystemExit(main())
