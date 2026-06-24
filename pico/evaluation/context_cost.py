"""Context A/B cost experiment helpers."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from pico import Pico, SessionStore, WorkspaceContext
from pico.config import resolve_provider_config
from pico.providers import AnthropicCompatibleModelClient, OpenAICompatibleModelClient
from pico.testing import ScriptedModelClient


@dataclass(frozen=True)
class ProviderPricing:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float


@dataclass(frozen=True)
class CostUsage:
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    usage_source: str
    model_call_count: int

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, int(self.input_tokens) - int(self.cached_tokens))


@dataclass(frozen=True)
class ExperimentRow:
    task_id: str
    layer: str
    variant: str
    repeat: int
    status: str
    verification_status: str
    tool_steps: int
    attempts: int
    prompt_estimated_tokens: int
    usage: CostUsage
    cost_usd: float
    saved_chars: int
    replacement_cache_hits: int
    summary_called: bool
    summary_delta_event_count: int
    report_path: str
    trace_path: str
    compact_call_input_tokens: int = 0
    compact_call_output_tokens: int = 0
    compact_net_benefit_tokens: int | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["usage"] = asdict(self.usage)
        return payload


DEFAULT_PROXY_PRICING = ProviderPricing(
    input_per_1m=2.0,
    cached_input_per_1m=0.2,
    output_per_1m=8.0,
)

EXPERIMENT_VARIANTS = {
    "no_context_reduction": {
        "description": "Baseline: no context reduction features",
        "context_reduction": False,
    },
    "full_orchestrator": {
        "description": "V1 context governance enabled",
        "context_reduction": True,
    },
}


def compute_cost_usd(usage: CostUsage, pricing: ProviderPricing) -> float:
    return (
        usage.uncached_input_tokens * pricing.input_per_1m
        + int(usage.cached_tokens) * pricing.cached_input_per_1m
        + int(usage.output_tokens) * pricing.output_per_1m
    ) / 1_000_000


def extract_usage_from_artifacts(
    report_path,
    trace_path,
    *,
    task_id,
    layer,
    variant,
    repeat,
    pricing,
    verification_status=None,
    allow_verification_override=False,
) -> ExperimentRow:
    report_path = Path(report_path)
    trace_path = Path(trace_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    trace_usage = _usage_from_trace(trace_path)
    compact_metrics = _compact_metrics_from_trace(trace_path)
    summary = dict(
        (report.get("evidence_summaries", {}) or {}).get("context_budget_summary", {})
        or {}
    )
    derived_verification = _verification_status(report)
    if allow_verification_override and verification_status is not None:
        derived_verification = str(verification_status)
    compact_call_tokens = int(compact_metrics.get("compact_call_input_tokens", 0) or 0) + int(
        compact_metrics.get("compact_call_output_tokens", 0) or 0
    )
    net = (
        int(summary.get("pre_tokens", 0) or 0)
        - int(summary.get("post_tokens", 0) or 0)
        - compact_call_tokens
        if summary
        else None
    )
    return ExperimentRow(
        task_id=str(task_id),
        layer=str(layer),
        variant=str(variant),
        repeat=int(repeat),
        status=str(report.get("status", "completed")),
        verification_status=derived_verification,
        tool_steps=int(report.get("tool_steps", 0) or 0),
        attempts=int(report.get("attempts", 0) or 0),
        prompt_estimated_tokens=int(trace_usage["estimated_input_tokens"]),
        usage=trace_usage["usage"],
        cost_usd=compute_cost_usd(trace_usage["usage"], pricing) if pricing else 0.0,
        saved_chars=int(summary.get("saved_chars", 0) or 0),
        replacement_cache_hits=int(summary.get("replacement_cache_hits", 0) or 0),
        summary_called=bool(summary.get("summary_called", False) or compact_metrics.get("summary_called", False)),
        summary_delta_event_count=int(summary.get("summary_delta_event_count", 0) or 0),
        compact_call_input_tokens=int(compact_metrics.get("compact_call_input_tokens", 0) or 0),
        compact_call_output_tokens=int(compact_metrics.get("compact_call_output_tokens", 0) or 0),
        compact_net_benefit_tokens=net,
        report_path=report_path.as_posix(),
        trace_path=trace_path.as_posix(),
    )


def summarize_paired_rows(
    rows, *, treatment="full_orchestrator", control="no_context_reduction"
):
    rows = list(rows)
    pairs = _paired_rows(rows, treatment=treatment, control=control)
    buckets = {
        "actual_only": [],
        "estimated_proxy_only": [],
        "mixed_or_invalid": [],
    }
    for pair in pairs:
        source = _pair_usage_source(pair, treatment, control)
        key = {
            "actual": "actual_only",
            "estimated_proxy": "estimated_proxy_only",
        }.get(source, "mixed_or_invalid")
        buckets[key].append(pair)
    return {
        name: _summarize_pair_bucket(pairs, treatment=treatment, control=control)
        for name, pairs in buckets.items()
    } | {
        "real_usage_row_count": sum(1 for row in rows if row.usage.usage_source == "actual"),
        "estimated_proxy_row_count": sum(1 for row in rows if row.usage.usage_source == "estimated_proxy"),
    }


def run_deterministic_prompt_experiment(output_dir, repetitions=1, pricing=None):
    pricing = pricing or DEFAULT_PROXY_PRICING
    output_dir = Path(output_dir)
    rows = []
    for repeat in range(int(repetitions)):
        for variant in ("full_orchestrator", "no_context_reduction"):
            workspace = output_dir / "work" / "prompt-only" / variant / str(repeat)
            workspace.mkdir(parents=True, exist_ok=True)
            agent = _build_synthetic_agent(
                workspace,
                context_reduction=EXPERIMENT_VARIANTS[variant]["context_reduction"],
            )
            prompt, prompt_metadata = agent._build_prompt_and_metadata("Summarize this workspace.")
            del prompt
            report_path = workspace / "report.json"
            trace_path = workspace / "trace.jsonl"
            _write_prompt_only_trace(trace_path, prompt_metadata)
            _write_prompt_only_report(report_path, prompt_metadata)
            rows.append(
                extract_usage_from_artifacts(
                    report_path,
                    trace_path,
                    task_id="prompt-only",
                    layer="deterministic",
                    variant=variant,
                    repeat=repeat,
                    pricing=pricing,
                    verification_status="passed",
                    allow_verification_override=True,
                )
            )
    return build_result_payload(rows, pricing_profile="proxy", pricing=pricing)


def run_scripted_e2e_experiment(output_dir, repetitions=1, pricing=None):
    pricing = pricing or DEFAULT_PROXY_PRICING
    output_dir = Path(output_dir)
    rows = []
    for repeat in range(int(repetitions)):
        for variant in ("full_orchestrator", "no_context_reduction"):
            workspace = output_dir / "work" / "scripted-large-read" / variant / str(repeat)
            workspace.mkdir(parents=True, exist_ok=True)
            agent = _build_scripted_agent(
                workspace,
                context_reduction=EXPERIMENT_VARIANTS[variant]["context_reduction"],
            )
            answer = agent.ask("Read large.txt and summarize it.")
            if answer != "done":
                raise AssertionError(f"unexpected scripted answer: {answer}")
            rows.append(
                extract_usage_from_artifacts(
                    agent.current_run_dir / "report.json",
                    agent.current_run_dir / "trace.jsonl",
                    task_id="scripted-large-read",
                    layer="scripted",
                    variant=variant,
                    repeat=repeat,
                    pricing=pricing,
                    verification_status="passed",
                    allow_verification_override=True,
                )
            )
    return build_result_payload(rows, pricing_profile="scripted-proxy", pricing=pricing)


def run_paired_experiment(
    tasks,
    *,
    variants=None,
    mode="scripted",
    provider=None,
    repetitions=1,
    output_dir=None,
    pricing=None,
    provider_client_factory=None,
):
    mode = str(mode)
    if mode not in {"scripted", "live"}:
        raise ValueError(f"unsupported experiment mode: {mode}")
    variants = list(variants or ["full_orchestrator", "no_context_reduction"])
    unknown = [variant for variant in variants if variant not in EXPERIMENT_VARIANTS]
    if unknown:
        raise ValueError(f"unknown experiment variant: {unknown[0]}")
    pricing = pricing or DEFAULT_PROXY_PRICING
    output_dir = Path(output_dir or "artifacts/context-ab-v1")
    rows = []
    for repeat in range(int(repetitions)):
        for task in tasks:
            for variant in variants:
                rows.append(
                    _run_task(
                        dict(task),
                        variant=variant,
                        repeat=repeat,
                        mode=mode,
                        provider=provider,
                        output_dir=output_dir,
                        pricing=pricing,
                        provider_client_factory=provider_client_factory,
                    )
                )
    return build_result_payload(
        rows,
        pricing_profile="actual" if mode == "live" else "scripted-proxy",
        pricing=pricing,
    )


def collect_rows_from_run_manifest(manifest, *, pricing):
    rows = []
    for item in manifest.get("runs", []) or []:
        rows.append(
            extract_usage_from_artifacts(
                item["report_path"],
                item["trace_path"],
                task_id=item["task_id"],
                layer=item.get("layer", "live"),
                variant=item["variant"],
                repeat=item.get("repeat", 0),
                pricing=pricing,
            )
        )
    return rows


def build_result_payload(
    rows,
    *,
    pricing_profile,
    pricing=None,
    treatment="full_orchestrator",
    control="no_context_reduction",
):
    rows = list(rows)
    return {
        "artifact_type": "context-ab-v1",
        "pricing_profile": str(pricing_profile),
        "pricing": asdict(pricing) if pricing else None,
        "summary": summarize_paired_rows(rows, treatment=treatment, control=control),
        "rows": [row.to_dict() for row in rows],
    }


def render_markdown_report(payload):
    summary = dict(payload.get("summary", {}) or {})
    actual = dict(summary.get("actual_only", {}) or {})
    proxy = dict(summary.get("estimated_proxy_only", {}) or {})
    mixed = dict(summary.get("mixed_or_invalid", {}) or {})
    benefit = actual if actual.get("paired_task_count", 0) else proxy
    baseline = float(benefit.get("total_input_tokens_per_task_control", 0) or 0)
    optimized = float(benefit.get("total_input_tokens_per_task_treatment", 0) or 0)
    compact_call_tokens = 0
    net_saved = baseline - optimized - compact_call_tokens
    net_pct = (net_saved / baseline) if baseline else 0.0
    return "\n".join(
        [
            "# Context A/B Cost Experiment",
            "",
            "## Summary",
            "",
            f"- Actual-only paired tasks: {actual.get('paired_task_count', 0)}",
            f"- Actual-only median cost delta: {actual.get('median_cost_delta_pct', 0):.2%}",
            f"- Actual-only claimable cost win: {actual.get('claimable_cost_win', False)}",
            f"- Estimated-proxy paired tasks: {proxy.get('paired_task_count', 0)}",
            f"- Estimated-proxy median cost delta: {proxy.get('median_cost_delta_pct', 0):.2%}",
            f"- Estimated-proxy claimable cost win: {proxy.get('claimable_cost_win', False)}",
            f"- Mixed/invalid paired tasks: {mixed.get('paired_task_count', 0)}",
            "",
            "## Net Benefit",
            "",
            "- Formula: net_saved = baseline_input_tokens - optimized_input_tokens - compact_call_tokens",
            "- compact_call_tokens: 0 (V1 deterministic compact, no LLM call)",
            f"- Baseline (no_context_reduction) avg input tokens/task: {baseline:.2f}",
            f"- Optimized (full_orchestrator) avg input tokens/task: {optimized:.2f}",
            f"- Net saved input tokens/task: {net_saved:.2f}",
            f"- Net saved percentage: {net_pct:.2%}",
            f"- Quality regression count: {benefit.get('quality_regression_count', 0)}",
            f"- Claimable cost win: {benefit.get('claimable_cost_win', False)}",
            "",
        ]
    )


def write_experiment_artifacts(payload, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "results.json"
    csv_path = output_dir / "paired_rows.csv"
    report_path = output_dir / "report.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_rows_csv(payload.get("rows", []), csv_path)
    report_path.write_text(render_markdown_report(payload), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "report": str(report_path)}


def _usage_from_trace(trace_path):
    events = _read_jsonl(trace_path)
    estimated = 0
    model_calls = []
    for event in events:
        if event.get("event") == "prompt_built":
            prompt_metadata = dict(event.get("prompt_metadata", {}) or {})
            context_usage = dict(prompt_metadata.get("context_usage", {}) or {})
            estimated += int(context_usage.get("total_estimated_tokens", 0) or 0)
        if event.get("event") == "model_parsed":
            metadata = dict(event.get("completion_metadata", {}) or {})
            if metadata:
                model_calls.append(metadata)
    actual_calls = [metadata for metadata in model_calls if _is_provider_usage_metadata(metadata)]
    if model_calls and len(actual_calls) == len(model_calls):
        usage = CostUsage(
            input_tokens=sum(int(call.get("input_tokens", 0) or 0) for call in actual_calls),
            cached_tokens=sum(int(call.get("cached_tokens", 0) or 0) for call in actual_calls),
            output_tokens=sum(int(call.get("output_tokens", 0) or 0) for call in actual_calls),
            usage_source="actual",
            model_call_count=len(actual_calls),
        )
        return {"usage": usage, "estimated_input_tokens": estimated or usage.input_tokens}
    return {
        "usage": CostUsage(
            input_tokens=estimated,
            cached_tokens=0,
            output_tokens=0,
            usage_source="estimated_proxy",
            model_call_count=len(model_calls),
        ),
        "estimated_input_tokens": estimated,
    }


def _compact_metrics_from_trace(trace_path):
    metrics = {
        "summary_called": False,
        "compact_call_input_tokens": 0,
        "compact_call_output_tokens": 0,
    }
    for event in _read_jsonl(trace_path):
        if str(event.get("event", "")).startswith("compaction_"):
            metrics["summary_called"] = True
    return metrics


def _is_provider_usage_metadata(metadata):
    if metadata.get("synthetic"):
        return False
    return metadata.get("input_tokens") is not None and metadata.get("output_tokens") is not None


def _verification_status(report):
    evidence = dict(report.get("evidence_summaries", {}) or {})
    verification = dict(evidence.get("verification_signal", {}) or {})
    state = str(verification.get("state", "")).strip()
    return state or "unknown"


def _paired_rows(rows, *, treatment, control):
    by_key = {}
    for row in rows:
        key = (row.task_id, row.repeat, row.layer)
        by_key.setdefault(key, {})[row.variant] = row
    return [
        variants
        for _, variants in sorted(by_key.items())
        if treatment in variants and control in variants
    ]


def _quality_regressed(treatment_row, control_row):
    if treatment_row.status != "completed" and control_row.status == "completed":
        return True
    if treatment_row.verification_status != "passed" and control_row.verification_status == "passed":
        return True
    if treatment_row.tool_steps > max(control_row.tool_steps * 3, control_row.tool_steps + 2):
        return True
    return False


def _summarize_pair_bucket(pairs, *, treatment, control):
    pairs = list(pairs)
    uncached_deltas = [
        _delta_pct(pair[treatment].usage.uncached_input_tokens, pair[control].usage.uncached_input_tokens)
        for pair in pairs
    ]
    cost_deltas = [
        _delta_pct(pair[treatment].cost_usd, pair[control].cost_usd)
        for pair in pairs
    ]
    return {
        "paired_task_count": len(pairs),
        "quality_regression_count": sum(1 for pair in pairs if _quality_regressed(pair[treatment], pair[control])),
        "unknown_verification_count": sum(
            1
            for pair in pairs
            if pair[treatment].verification_status == "unknown"
            or pair[control].verification_status == "unknown"
        ),
        "success_rate_treatment": _rate(pair[treatment].status == "completed" for pair in pairs),
        "success_rate_control": _rate(pair[control].status == "completed" for pair in pairs),
        "verifier_pass_rate_treatment": _rate(pair[treatment].verification_status == "passed" for pair in pairs),
        "verifier_pass_rate_control": _rate(pair[control].verification_status == "passed" for pair in pairs),
        "avg_tool_steps_treatment": _mean_rounded(pair[treatment].tool_steps for pair in pairs),
        "avg_tool_steps_control": _mean_rounded(pair[control].tool_steps for pair in pairs),
        "avg_attempts_treatment": _mean_rounded(pair[treatment].attempts for pair in pairs),
        "avg_attempts_control": _mean_rounded(pair[control].attempts for pair in pairs),
        "cost_per_successful_task_treatment": _cost_per_successful_task(pair[treatment] for pair in pairs),
        "cost_per_successful_task_control": _cost_per_successful_task(pair[control] for pair in pairs),
        "billable_input_tokens_per_task_treatment": _mean_rounded(pair[treatment].usage.uncached_input_tokens for pair in pairs),
        "billable_input_tokens_per_task_control": _mean_rounded(pair[control].usage.uncached_input_tokens for pair in pairs),
        "total_input_tokens_per_task_treatment": _mean_rounded(pair[treatment].usage.input_tokens for pair in pairs),
        "total_input_tokens_per_task_control": _mean_rounded(pair[control].usage.input_tokens for pair in pairs),
        "output_tokens_per_task_treatment": _mean_rounded(pair[treatment].usage.output_tokens for pair in pairs),
        "output_tokens_per_task_control": _mean_rounded(pair[control].usage.output_tokens for pair in pairs),
        "median_uncached_input_delta_pct": _median_rounded(uncached_deltas),
        "p95_uncached_input_delta_pct": _p95_rounded(uncached_deltas),
        "median_cost_delta_pct": _median_rounded(cost_deltas),
        "claimable_cost_win": _claimable_cost_win(pairs, treatment=treatment, control=control, cost_deltas=cost_deltas),
    }


def _pair_usage_source(pair, treatment, control):
    sources = {pair[treatment].usage.usage_source, pair[control].usage.usage_source}
    if sources == {"actual"}:
        return "actual"
    if sources == {"estimated_proxy"}:
        return "estimated_proxy"
    return "mixed_or_invalid"


def _claimable_cost_win(pairs, *, treatment, control, cost_deltas):
    if not pairs or not cost_deltas or _median_rounded(cost_deltas) >= 0:
        return False
    if any(
        pair[treatment].compact_net_benefit_tokens is not None
        and int(pair[treatment].compact_net_benefit_tokens) < 0
        for pair in pairs
    ):
        return False
    if any(_quality_regressed(pair[treatment], pair[control]) for pair in pairs):
        return False
    return all(
        pair[treatment].verification_status == "passed"
        and pair[control].verification_status == "passed"
        for pair in pairs
    )


def _delta_pct(treatment, control):
    if not control:
        return 0.0
    return round((float(treatment) - float(control)) / float(control), 4)


def _median_rounded(values):
    return round(statistics.median(values), 4) if values else 0.0


def _mean_rounded(values):
    values = list(values)
    return round(statistics.mean(values), 4) if values else 0.0


def _rate(values):
    values = list(values)
    return round(sum(1 for value in values if value) / len(values), 4) if values else 0.0


def _cost_per_successful_task(rows):
    rows = list(rows)
    successful = [row for row in rows if row.status == "completed" and row.verification_status == "passed"]
    if not successful:
        return 0.0
    return round(sum(row.cost_usd for row in rows) / len(successful), 8)


def _p95_rounded(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 4)


def _build_synthetic_agent(workspace_root, *, context_reduction=True):
    workspace_root = Path(workspace_root)
    (workspace_root / "README.md").write_text("demo\n", encoding="utf-8")
    agent = Pico(
        model_client=ScriptedModelClient(["<final>done</final>"]),
        workspace=WorkspaceContext.build(workspace_root),
        session_store=SessionStore(workspace_root / ".pico" / "sessions"),
        approval_policy="auto",
        feature_flags={"context_reduction": context_reduction},
        max_steps=1,
    )
    for index in range(10):
        agent.record({"role": "user", "content": f"prior request {index} " + ("u" * 500)})
        agent.record({"role": "assistant", "content": f"prior answer {index} " + ("a" * 500)})
    return agent


class _ContextCostScriptedClient(ScriptedModelClient):
    def __init__(self):
        super().__init__([])
        self.phase = 0

    def complete(self, prompt, max_new_tokens, **kwargs):
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        self.last_completion_metadata = {
            "input_tokens": max(1, len(prompt) // 4),
            "cached_tokens": 0,
            "output_tokens": 32,
            "synthetic": True,
        }
        if self.phase == 0:
            self.phase += 1
            return '<tool>{"name":"read_file","args":{"path":"large.txt","start":1,"end":200}}</tool>'
        return "<final>done</final>"


def _build_scripted_agent(workspace_root, *, context_reduction=True):
    workspace_root = Path(workspace_root)
    (workspace_root / "README.md").write_text("demo\n", encoding="utf-8")
    (workspace_root / "large.txt").write_text(("large context line\n" * 260), encoding="utf-8")
    agent = Pico(
        model_client=_ContextCostScriptedClient(),
        workspace=WorkspaceContext.build(workspace_root),
        session_store=SessionStore(workspace_root / ".pico" / "sessions"),
        approval_policy="auto",
        feature_flags={"context_reduction": context_reduction},
        max_steps=4,
        allowed_tools=["read_file"],
    )
    for index in range(10):
        agent.record({"role": "user", "content": f"prior request {index} " + ("u" * 500)})
        agent.record({"role": "assistant", "content": f"prior answer {index} " + ("a" * 500)})
    return agent


def _run_task(
    task,
    *,
    variant,
    repeat,
    mode,
    provider,
    output_dir,
    pricing,
    provider_client_factory=None,
):
    workspace = Path(output_dir) / "work" / str(task.get("id", "task")) / variant / str(repeat)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.md").write_text("demo\n", encoding="utf-8")
    (workspace / "large.txt").write_text(str(task.get("content", "large context line\n" * 260)), encoding="utf-8")
    client = (
        _ContextCostScriptedClient()
        if mode == "scripted"
        else (provider_client_factory(provider=provider, task=task, variant=variant, repeat=repeat) if provider_client_factory else _build_live_provider_client(provider))
    )
    agent = Pico(
        model_client=client,
        workspace=WorkspaceContext.build(workspace),
        session_store=SessionStore(workspace / ".pico" / "sessions"),
        approval_policy="auto",
        feature_flags={"context_reduction": EXPERIMENT_VARIANTS[variant]["context_reduction"]},
        max_steps=4,
        allowed_tools=["read_file"],
    )
    for index in range(10):
        agent.record({"role": "user", "content": f"prior request {index} " + ("u" * 500)})
        agent.record({"role": "assistant", "content": f"prior answer {index} " + ("a" * 500)})
    answer = agent.ask(str(task.get("prompt", "Read large.txt and summarize it.")))
    verification = "passed" if mode == "scripted" and answer == "done" else "unknown"
    return extract_usage_from_artifacts(
        agent.current_run_dir / "report.json",
        agent.current_run_dir / "trace.jsonl",
        task_id=task.get("id", "task"),
        layer=mode,
        variant=variant,
        repeat=repeat,
        pricing=pricing,
        verification_status=verification,
        allow_verification_override=True,
    )


def _build_live_provider_client(provider):
    config = resolve_provider_config(provider, start=Path.cwd())
    if not config.api_key:
        raise RuntimeError(f"live provider config blocked: API key missing for provider profile {config.name}")
    if config.protocol == "openai":
        return OpenAICompatibleModelClient(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            temperature=0.0,
            timeout=300,
        )
    if config.protocol == "anthropic":
        return AnthropicCompatibleModelClient(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            temperature=0.0,
            timeout=300,
        )
    raise RuntimeError(f"live provider config blocked: unsupported protocol {config.protocol}")


def _write_prompt_only_trace(trace_path, prompt_metadata):
    trace_path.write_text(
        json.dumps({"event": "prompt_built", "prompt_metadata": prompt_metadata}) + "\n",
        encoding="utf-8",
    )


def _write_prompt_only_report(report_path, prompt_metadata):
    report_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "tool_steps": 0,
                "attempts": 0,
                "prompt_metadata": prompt_metadata,
                "evidence_summaries": {"verification_signal": {"state": "passed"}},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_rows_csv(rows, csv_path):
    fieldnames = [
        "task_id",
        "layer",
        "variant",
        "repeat",
        "status",
        "verification_status",
        "input_tokens",
        "cached_tokens",
        "output_tokens",
        "usage_source",
        "cost_usd",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            usage = dict(row.get("usage", {}) or {})
            writer.writerow(
                {
                    "task_id": row.get("task_id", ""),
                    "layer": row.get("layer", ""),
                    "variant": row.get("variant", ""),
                    "repeat": row.get("repeat", 0),
                    "status": row.get("status", ""),
                    "verification_status": row.get("verification_status", ""),
                    "input_tokens": usage.get("input_tokens", 0),
                    "cached_tokens": usage.get("cached_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "usage_source": usage.get("usage_source", ""),
                    "cost_usd": row.get("cost_usd", 0.0),
                }
            )


def _read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_arg_parser():
    parser = argparse.ArgumentParser(description="Run Pico context A/B cost experiments.")
    parser.add_argument("--mode", choices=("deterministic", "scripted", "manifest"), default="deterministic")
    parser.add_argument("--output-dir", default="artifacts/context-ab-v1")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--manifest")
    return parser


def main(argv=None):
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.mode == "deterministic":
        payload = run_deterministic_prompt_experiment(args.output_dir, repetitions=args.repetitions)
    elif args.mode == "scripted":
        payload = run_scripted_e2e_experiment(args.output_dir, repetitions=args.repetitions)
    else:
        if not args.manifest:
            parser.error("--manifest is required for manifest mode")
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        rows = collect_rows_from_run_manifest(manifest, pricing=DEFAULT_PROXY_PRICING)
        payload = build_result_payload(rows, pricing_profile="manifest", pricing=DEFAULT_PROXY_PRICING)
    written = write_experiment_artifacts(payload, args.output_dir)
    print(json.dumps(written, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
