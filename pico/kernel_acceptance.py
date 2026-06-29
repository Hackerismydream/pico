"""Live-provider acceptance harness for the kernel runtime."""

import argparse
import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .cli import PROVIDER_CHOICES, _build_model_client, _effective_model
from .config import load_project_env
from .runtime_kernel import InvocationContext, RuntimeRunner, ToolPermissionPolicy, ToolRuntime
from .workspace import WorkspaceContext


SCENARIOS = ("no-tool", "read-only-tool")
CREDENTIAL_ENV_NAMES = {
    "openai": (
        "PICO_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "PICO_RIGHT_CODES_API_KEY",
        "RIGHT_CODES_API_KEY",
        "PICO_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
    ),
    "anthropic": (
        "PICO_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
        "PICO_RIGHT_CODES_API_KEY",
        "RIGHT_CODES_API_KEY",
        "PICO_OPENAI_API_KEY",
        "OPENAI_API_KEY",
    ),
    "deepseek": ("PICO_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
}
READONLY_MARKER = "pico-kernel-readonly-acceptance-marker"


@dataclass(frozen=True)
class CredentialCheck:
    status: str
    reason: str = ""


def credential_status(provider):
    names = CREDENTIAL_ENV_NAMES.get(str(provider), ())
    if not names:
        return CredentialCheck(status="present")
    if any(os.environ.get(name) for name in names):
        return CredentialCheck(status="present")
    return CredentialCheck(
        status="missing",
        reason=f"missing credentials for provider '{provider}': set one of {', '.join(names)}",
    )


def run_kernel_acceptance(
    *,
    provider,
    model,
    model_client_factory: Callable[[str], object],
    scenarios=SCENARIOS,
    workspace_root=None,
    max_new_tokens=256,
    max_steps=4,
):
    scenario_names = _normalize_scenarios(scenarios)
    base_workspace = Path(workspace_root) if workspace_root is not None else None
    reports = []
    for scenario in scenario_names:
        with _scenario_workspace(scenario, base_workspace) as scenario_workspace:
            reports.append(
                _run_scenario(
                    scenario=scenario,
                    workspace_root=scenario_workspace,
                    provider=provider,
                    model=model,
                    model_client=model_client_factory(scenario),
                    max_new_tokens=max_new_tokens,
                    max_steps=max_steps,
                )
            )
    status = "passed" if all(report["status"] == "passed" for report in reports) else "failed"
    return {
        "status": status,
        "run_id": _new_acceptance_run_id(),
        "provider": provider,
        "model": model,
        "scenarios": reports,
    }


def skipped_report(*, provider, model, reason):
    return {
        "status": "skipped",
        "run_id": _new_acceptance_run_id(),
        "provider": provider,
        "model": model,
        "reason": reason,
        "scenarios": [],
    }


def _new_acceptance_run_id():
    return f"acceptance_{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _run_scenario(*, scenario, workspace_root, provider, model, model_client, max_new_tokens, max_steps):
    context = InvocationContext(
        user_message=_scenario_prompt(scenario),
        workspace_root=str(workspace_root),
        max_new_tokens=max_new_tokens,
        max_steps=max_steps,
    )
    runner = RuntimeRunner(
        model_client=model_client,
        tool_runtime=ToolRuntime(
            workspace_root,
            permission_policy=ToolPermissionPolicy.allow_readonly("kernel acceptance allows read-only tools"),
        ),
    )
    result = runner.run(context)
    metadata = _last_model_metadata(result.events)
    tool_results = [event.payload for event in result.events if event.type == "tool_result"]
    failure_reason = _scenario_failure_reason(scenario, result, tool_results)
    status = "passed" if not failure_reason else "failed"
    return {
        "name": scenario,
        "status": status,
        "failure_reason": failure_reason,
        "run_id": context.invocation_id,
        "provider": provider,
        "model": model,
        "runtime_status": result.status,
        "finish_reason": metadata.get("finish_reason") or "",
        "provider_status": metadata.get("provider_status") or result.status,
        "usage": _usage_from_metadata(metadata),
        "provider_metadata": metadata,
        "tool_result_count": len(tool_results),
        "final_answer": result.final_answer,
        "error_type": result.error_type,
        "error_message": result.error_message,
    }


def _scenario_failure_reason(scenario, result, tool_results):
    if result.status != "completed":
        return result.error_type or result.error_message or "runtime did not complete"
    if scenario == "no-tool" and tool_results:
        return "no-tool acceptance unexpectedly executed a tool"
    if scenario == "read-only-tool":
        ok_tool_results = [payload for payload in tool_results if payload.get("status") == "ok"]
        if not ok_tool_results:
            return "read-only acceptance did not complete a read-only tool call"
        if READONLY_MARKER not in result.final_answer:
            return "read-only acceptance final answer did not include the workspace marker"
    return ""


def _scenario_prompt(scenario):
    if scenario == "no-tool":
        return (
            "Kernel live acceptance no-tool check. Do not inspect the workspace. "
            "Reply with <final>pico kernel no-tool acceptance ok</final>."
        )
    if scenario == "read-only-tool":
        return (
            "Kernel live acceptance read-only-tool check. Use the read_file tool on README.md before answering. "
            f"Then reply with a <final> answer that includes this exact marker: {READONLY_MARKER}."
        )
    raise ValueError(f"unknown acceptance scenario: {scenario}")


class _scenario_workspace:
    def __init__(self, scenario, base_workspace):
        self.scenario = scenario
        self.base_workspace = None if base_workspace is None else Path(base_workspace)
        self._tmpdir = None

    def __enter__(self):
        if self.base_workspace is None:
            self._tmpdir = tempfile.TemporaryDirectory(prefix=f"pico-{self.scenario}-acceptance-")
            root = Path(self._tmpdir.name)
        else:
            root = self.base_workspace
            root.mkdir(parents=True, exist_ok=True)
        if self.scenario == "read-only-tool":
            (root / "README.md").write_text(
                f"# Pico Kernel Acceptance\n\nmarker: {READONLY_MARKER}\n",
                encoding="utf-8",
            )
        return root

    def __exit__(self, exc_type, exc, traceback):
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


def _last_model_metadata(events):
    for event in reversed(events):
        if event.type == "model_output":
            return dict(event.payload.get("metadata") or {})
    return {}


def _usage_from_metadata(metadata):
    return {
        key: metadata.get(key)
        for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "cache_hit")
        if key in metadata
    }


def _normalize_scenarios(scenarios):
    if isinstance(scenarios, str):
        scenarios = (scenarios,)
    names = tuple(SCENARIOS if scenario == "all" else scenario for scenario in scenarios)
    flattened = []
    for name in names:
        if isinstance(name, tuple):
            flattened.extend(name)
        else:
            flattened.append(name)
    unknown = [name for name in flattened if name not in SCENARIOS]
    if unknown:
        raise ValueError(f"unknown acceptance scenario: {', '.join(unknown)}")
    return tuple(flattened)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Run kernel runtime live-provider acceptance.",
    )
    parser.add_argument("--cwd", default=".", help="Project directory whose .env should be loaded.")
    parser.add_argument("--provider", choices=PROVIDER_CHOICES, default="deepseek", help="Provider to test.")
    parser.add_argument("--model", default=None, help="Model override for the selected provider.")
    parser.add_argument("--base-url", default=None, help="Provider API base URL override.")
    parser.add_argument("--host", default="http://127.0.0.1:11434", help="Ollama host.")
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all", help="Acceptance scenario to run.")
    parser.add_argument("--max-steps", type=int, default=4, help="Maximum kernel model/tool iterations.")
    parser.add_argument("--max-new-tokens", type=int, default=256, help="Maximum model output tokens per step.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Top-p sampling value for Ollama.")
    parser.add_argument("--ollama-timeout", type=int, default=300, help="Ollama request timeout in seconds.")
    parser.add_argument("--openai-timeout", type=int, default=300, help="HTTP provider request timeout in seconds.")
    return parser


def main(argv=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_arg_parser().parse_args(argv)
    workspace = WorkspaceContext.build(args.cwd)
    load_project_env(workspace.repo_root)
    provider = args.provider
    model = _effective_model(args, provider)
    credentials = credential_status(provider)
    if credentials.status != "present":
        report = skipped_report(provider=provider, model=model, reason=credentials.reason)
        print(json.dumps(report, indent=2, sort_keys=True), file=stdout)
        print(credentials.reason, file=stderr)
        return 2
    report = run_kernel_acceptance(
        provider=provider,
        model=model,
        model_client_factory=lambda scenario: _build_model_client(args),
        scenarios=(args.scenario,),
        max_new_tokens=args.max_new_tokens,
        max_steps=args.max_steps,
    )
    print(json.dumps(report, indent=2, sort_keys=True), file=stdout)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
