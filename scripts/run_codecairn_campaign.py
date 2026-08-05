from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from benchmarks.picobench.campaign import CampaignMode
from benchmarks.picobench.canonical import to_primitive
from benchmarks.picobench.codecairn_campaign import (
    run_codecairn_campaign,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("smoke", "calibration", "ship"),
        default="ship",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    outcome = asyncio.run(
        run_codecairn_campaign(
            CampaignMode(args.mode),
            output_root=args.output_root,
        )
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
