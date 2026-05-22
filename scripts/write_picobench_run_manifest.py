#!/usr/bin/env python3
"""Write redacted PicoBench live-run manifest files."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from pico.config import load_project_env, resolve_provider_config


ROOT = Path(__file__).resolve().parents[1]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write PicoBench run_manifest.json and provider_config_redacted.json.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--suite", default=None)
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--approval", default="")
    parser.add_argument("--sandbox", default="")
    parser.add_argument("--notes", default="")
    return parser


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    load_project_env(ROOT, override=False)
    summary = _read_json(output_dir / "summary.json")
    provider_name = args.provider or summary.get("provider") or None
    provider_config = resolve_provider_config(provider_name, start=ROOT, model=args.model or summary.get("model") or None)
    benchmark = args.benchmark or ""
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repo_commit": _git_value(["rev-parse", "HEAD"]),
        "branch": _git_value(["branch", "--show-current"]),
        "suite": args.suite or summary.get("suite") or "",
        "benchmark": benchmark,
        "provider": provider_config.name,
        "model": provider_config.model,
        "approval": args.approval,
        "sandbox": args.sandbox,
        "task_count": int(summary.get("task_count") or 0),
        "summary_path": "summary.json",
        "evidence_paths": _relative_evidence_paths(output_dir),
        "notes": args.notes,
    }
    provider_redacted = {
        "provider": provider_config.name,
        "protocol": provider_config.protocol,
        "model": provider_config.model,
        "base_url_host": urlparse(provider_config.base_url).netloc,
        "has_api_key": bool(provider_config.api_key),
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "provider_config_redacted.json").write_text(
        json.dumps(provider_redacted, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(output_dir), "manifest": str(output_dir / "run_manifest.json")}, sort_keys=True))
    return 0


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_evidence_paths(output_dir: Path) -> list[str]:
    evidence_dir = output_dir / "evidence"
    if not evidence_dir.exists():
        return []
    return sorted(str(path.relative_to(output_dir)) for path in evidence_dir.iterdir() if path.is_dir())


def _git_value(args: list[str]) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True, timeout=5)
        return completed.stdout.strip()
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
