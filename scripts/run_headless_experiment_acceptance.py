#!/usr/bin/env python3
"""Run manual live-provider acceptance for headless experiments."""

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pico.cli import _effective_model
from pico.config import load_project_env
from pico.headless_experiment import HeadlessExperimentRunner, load_headless_experiment_spec


READONLY_MARKER = "pico-headless-experiment-readonly-acceptance-marker"


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _python_check(expression):
    return f"python3 -c \"import os, sys; sys.exit(0 if ({expression}) else 1)\""


def _candidate(args, model):
    candidate = {
        "id": f"{args.provider}-{model}",
        "provider_id": args.provider,
        "model_id": model,
    }
    if args.base_url:
        candidate["base_url"] = args.base_url
    if args.host:
        candidate["host"] = args.host
    if args.timeout:
        candidate["timeout"] = args.timeout
    candidate["temperature"] = args.temperature
    candidate["top_p"] = args.top_p
    return candidate


def _write_specs(args, root, model):
    inputs = root / "inputs"
    no_tool_workspace = inputs / "workspace-no-tool"
    no_tool_workspace.mkdir(parents=True, exist_ok=True)
    read_only_workspace = inputs / "workspace-read-only"
    read_only_workspace.mkdir(parents=True, exist_ok=True)
    (read_only_workspace / "README.md").write_text(
        f"# Pico Headless Experiment Acceptance\n\nmarker: {READONLY_MARKER}\n",
        encoding="utf-8",
    )

    no_tool_task = _write_json(
        inputs / "task-no-tool.json",
        {
            "id": "live_no_tool",
            "workspace": str(no_tool_workspace),
            "prompt": "unused; candidate prompt replaces this",
            "verifier": _python_check(
                "'pico headless experiment no-tool acceptance ok' in os.environ.get('PICO_FINAL_ANSWER', '')"
            ),
            "max_steps": args.max_steps,
            "max_new_tokens": args.max_new_tokens,
        },
    )
    read_only_task = _write_json(
        inputs / "task-read-only.json",
        {
            "id": "live_read_only_tool",
            "workspace": str(read_only_workspace),
            "prompt": "unused; candidate prompt replaces this",
            "verifier": _python_check(f"{READONLY_MARKER!r} in os.environ.get('PICO_FINAL_ANSWER', '')"),
            "allowed_tools": ["read_file"],
            "max_steps": args.max_steps,
            "max_new_tokens": args.max_new_tokens,
        },
    )

    base_candidate = _candidate(args, model)
    specs = []
    specs.append(
        _write_json(
            inputs / "experiment-no-tool.json",
            {
                "id": "live-provider-no-tool",
                "task": str(no_tool_task),
                "candidates": [
                    {
                        **base_candidate,
                        "prompt": (
                            "Headless experiment live-provider no-tool check. "
                            "Do not inspect the workspace. Reply with "
                            "<final>pico headless experiment no-tool acceptance ok</final>."
                        ),
                    }
                ],
            },
        )
    )
    specs.append(
        _write_json(
            inputs / "experiment-read-only.json",
            {
                "id": "live-provider-read-only-tool",
                "task": str(read_only_task),
                "candidates": [
                    {
                        **base_candidate,
                        "prompt": (
                            "Headless experiment live-provider read-only-tool check. "
                            "Use the read_file tool on README.md before answering. "
                            f"Then reply with a <final> answer that includes this exact marker: {READONLY_MARKER}."
                        ),
                    }
                ],
            },
        )
    )
    return specs


def _aggregate(results):
    summary = {
        "total_runs": 0,
        "passed": 0,
        "benchmark_failed": 0,
        "infrastructure_failed": 0,
        "skipped": 0,
        "reused": 0,
        "scored_runs": 0,
    }
    for result in results:
        for key in summary:
            summary[key] += int(result["summary"].get(key, 0) or 0)
    summary["benchmark_pass_rate"] = (
        summary["passed"] / summary["scored_runs"]
        if summary["scored_runs"]
        else None
    )
    return summary


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Run no-tool and read-only-tool live-provider headless experiment acceptance.",
    )
    parser.add_argument("--cwd", default=".", help="Project directory whose .env should be loaded.")
    parser.add_argument("--provider", choices=("openai", "anthropic", "deepseek", "ollama"), default="deepseek")
    parser.add_argument("--model", default=None, help="Model override for the selected provider.")
    parser.add_argument("--base-url", default=None, help="Provider API base URL override.")
    parser.add_argument("--host", default=None, help="Ollama host override.")
    parser.add_argument("--timeout", type=int, default=300, help="Provider request timeout in seconds.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Provider sampling temperature.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Provider top-p value.")
    parser.add_argument("--max-steps", type=int, default=4, help="Maximum kernel model/tool iterations.")
    parser.add_argument("--max-new-tokens", type=int, default=256, help="Maximum model output tokens per step.")
    parser.add_argument(
        "--runs-root",
        default=".pico/headless/live-provider-acceptance",
        help="Directory where acceptance experiment artifacts are written.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    cwd = Path(args.cwd).resolve()
    load_project_env(cwd)
    model = args.model or _effective_model(SimpleNamespace(model=None), args.provider)
    root = Path(args.runs_root)
    if not root.is_absolute():
        root = cwd / root
    specs = _write_specs(args, root, model)
    runner = HeadlessExperimentRunner(root / "experiments")
    exports = []
    for spec_path in specs:
        result = runner.run(load_headless_experiment_spec(spec_path))
        exports.append(result.export)
    report = {
        "artifact_type": "headless-experiment-live-provider-acceptance",
        "schema_version": 1,
        "provider": args.provider,
        "model": model,
        "summary": _aggregate(exports),
        "experiments": [
            {
                "experiment_run_id": export["experiment_run_id"],
                "experiment": export["experiment"],
                "summary": export["summary"],
                "artifacts": export["artifacts"],
            }
            for export in exports
        ],
    }
    report_path = _write_json(root / "headless_experiment_acceptance.json", report)
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["summary"]["skipped"]:
        return 2
    if report["summary"]["infrastructure_failed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
