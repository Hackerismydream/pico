#!/usr/bin/env python3
"""Prepare or run PicoBench ablation variants."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


VARIANTS = [
    "pico-full",
    "pico-no-memory",
    "pico-no-plan",
    "pico-no-subagent",
    "pico-no-skills",
]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or plan PicoBench ablations.")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--suite", default="core")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": 1,
        "benchmark": args.benchmark,
        "suite": args.suite,
        "provider": args.provider or "",
        "model": args.model or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "plan-only" if args.plan_only else "planned",
        "variants": [
            {
                "variant": variant,
                "status": "planned",
                "reason": "runtime feature flag not wired in this first PicoBench branch",
                "metrics": {
                    "solve@1_strict": None,
                    "solve@3_strict": None,
                    "functional_pass_rate": None,
                    "safety_violation_rate": None,
                    "evidence_consistency_rate": None,
                    "avg_tool_steps": None,
                    "avg_cost_usd": None,
                    "avg_wall_time_ms": None,
                    "failure_category_counts": {},
                },
            }
            for variant in VARIANTS
        ],
    }
    (output_dir / "ablation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "ablation_summary.md").write_text(_markdown(summary), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "variant_count": len(VARIANTS), "status": "planned"}, sort_keys=True))
    return 0


def _markdown(summary: dict) -> str:
    lines = [
        "# PicoBench Ablation Summary",
        "",
        f"- suite: {summary['suite']}",
        f"- benchmark: {summary['benchmark']}",
        f"- mode: {summary['mode']}",
        "",
        "| Variant | Status | Reason |",
        "|---|---|---|",
    ]
    for row in summary["variants"]:
        lines.append(f"| {row['variant']} | {row['status']} | {row['reason']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
