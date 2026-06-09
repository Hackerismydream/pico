#!/usr/bin/env python3
"""Select a stratified SWE-bench A/B smoke slice from an official eval report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-report", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--empty-count", type=int, default=10)
    parser.add_argument("--resolved-count", type=int, default=5)
    parser.add_argument("--unresolved-count", type=int, default=5)
    args = parser.parse_args(argv)

    result = select_slice(
        Path(args.eval_report),
        empty_count=args.empty_count,
        resolved_count=args.resolved_count,
        unresolved_count=args.unresolved_count,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def select_slice(
    eval_report: Path,
    *,
    empty_count: int = 10,
    resolved_count: int = 5,
    unresolved_count: int = 5,
) -> dict[str, Any]:
    payload = json.loads(eval_report.read_text(encoding="utf-8"))
    empty = _take_ids(payload, "empty_patch_ids", empty_count)
    resolved = _take_ids(payload, "resolved_ids", resolved_count)
    unresolved = _take_ids(payload, "unresolved_ids", unresolved_count)
    ids = empty + resolved + unresolved
    return {
        "source_eval_report": str(eval_report),
        "counts": {
            "empty_patch": len(empty),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "total": len(ids),
        },
        "ids": ids,
        "groups": {
            "empty_patch": empty,
            "resolved": resolved,
            "unresolved": unresolved,
        },
        "filter_regex": "^(?:" + "|".join(re.escape(instance_id) for instance_id in ids) + ")$",
    }


def _take_ids(payload: dict[str, Any], key: str, count: int) -> list[str]:
    ids = payload.get(key)
    if not isinstance(ids, list):
        raise ValueError(f"eval report is missing list field: {key}")
    return sorted(str(item) for item in ids)[: max(count, 0)]


if __name__ == "__main__":
    raise SystemExit(main())
