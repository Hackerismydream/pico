#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.picobench.codecairn_continuity import run_continuity_gate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pico-wheel", type=Path, required=True)
    parser.add_argument("--codecairn-wheel", type=Path, required=True)
    parser.add_argument("--codecairn-baseline-wheel", type=Path)
    parser.add_argument("--pico-handoff", type=Path, required=True)
    parser.add_argument("--codecairn-handoff", type=Path, required=True)
    parser.add_argument(
        "--pico-implementation-wheel",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--pico-compatibility-wheel",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--pico-distribution-report",
        type=Path,
        required=True,
    )
    parser.add_argument("--pico-commit", required=True)
    parser.add_argument("--pico-source-root", type=Path, required=True)
    parser.add_argument("--codecairn-source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = run_continuity_gate(
        pico_wheel=args.pico_wheel,
        codecairn_wheel=args.codecairn_wheel,
        pico_handoff=args.pico_handoff,
        codecairn_handoff=args.codecairn_handoff,
        pico_implementation_wheel=args.pico_implementation_wheel,
        pico_compatibility_wheel=args.pico_compatibility_wheel,
        pico_distribution_report=args.pico_distribution_report,
        pico_commit=args.pico_commit,
        pico_source_root=args.pico_source_root,
        codecairn_source_root=args.codecairn_source_root,
        output_root=args.output_root,
        codecairn_baseline_wheel=args.codecairn_baseline_wheel,
    )
    print(
        json.dumps(
            {
                "pair_manifest": str(result.pair_manifest),
                "pair_manifest_sha256": result.pair_manifest_sha256,
                "summary": str(result.summary),
                "summary_sha256": result.summary_sha256,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
