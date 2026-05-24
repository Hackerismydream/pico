#!/usr/bin/env python3
"""Create a PicoBench dogfood task skeleton."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a PicoBench dogfood task directory template.")
    parser.add_argument("--task-id", required=True, help="Task id, for example core_041.")
    parser.add_argument("--name", required=True, help="Visible fixture directory name.")
    parser.add_argument("--category", default="bugfix")
    parser.add_argument("--source-commit", default="", help="Original Pico commit or reference patch id.")
    parser.add_argument("--prompt", default="TODO: write a user-style dogfood prompt without hidden-test leakage.")
    parser.add_argument("--force", action="store_true", help="Allow writing into existing empty directories.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fixture = ROOT / "tests" / "fixtures" / "picobench" / args.name
    hidden = ROOT / "tests" / "fixtures" / "picobench_hidden" / args.task_id / "hidden_tests"
    _mkdir(fixture / "tests", force=args.force)
    _mkdir(hidden, force=args.force)
    _write(fixture / "README.md", f"# {args.task_id}\n\nSource: {args.source_commit or 'TODO'}\n", force=args.force)
    _write(fixture / "tests" / "test_public.py", "def test_public_behavior():\n    assert False\n", force=args.force)
    _write(hidden / "test_hidden.py", "def test_hidden_behavior():\n    assert False\n", force=args.force)
    stub = {
        "task_id": args.task_id,
        "title": "TODO dogfood task title",
        "suite": "picobench-core",
        "category": args.category,
        "repo": {
            "fixture": f"tests/fixtures/picobench/{args.name}",
            "hidden_fixture": f"tests/fixtures/picobench_hidden/{args.task_id}",
        },
        "prompt": {"text": args.prompt},
        "execution": {"driver": "one_shot_cli", "approval": "auto", "sandbox": "best_effort", "max_steps": 32, "timeout_sec": 360},
        "tests": {"public": ["python -m pytest tests -q"], "hidden": ["python -m pytest hidden_tests -q"]},
        "verifiers": [
            {"type": "evidence"},
            {"type": "changed_paths", "any": ["TODO"]},
            {"type": "forbidden_paths", "paths": [".env"]},
            {"type": "required_tool_sequence", "sequence": ["read_file", "run_shell"]},
            {"type": "must_run_tests"},
            {"type": "must_read_before_write"},
        ],
        "expected": {"changed_paths": {"any": ["TODO"]}, "stop_reason": "final_answer_returned"},
        "metadata": {
            "source": "pico-dogfood-derived",
            "source_commit": args.source_commit,
            "contamination_risk": "medium",
            "issue_clarity": "draft",
            "test_coverage": "draft",
        },
    }
    print(json.dumps(stub, indent=2, ensure_ascii=False))
    return 0


def _mkdir(path: Path, *, force: bool) -> None:
    if path.exists() and any(path.iterdir()) and not force:
        raise SystemExit(f"refusing to use non-empty directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _write(path: Path, text: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite: {path}")
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
