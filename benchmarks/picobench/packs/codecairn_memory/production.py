from __future__ import annotations

import asyncio
import hashlib
import http.server
import json
import os
import secrets
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import tomllib
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

import certifi
import httpx

from benchmarks.picobench.budget import (
    BudgetGuardedProvider,
    ProviderBudgetLedger,
    _conservative_serialized_input_tokens,
)
from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.codecairn_continuity import (
    PairIntegrityError,
    _command_json,
    _init_git_repository,
    _install_pair,
    _pico_source_journal,
    _public_journal_state,
    _read_json,
    _run,
    _sha256,
    _worker,
)
from benchmarks.picobench.isolation import TrialIsolation
from benchmarks.picobench.protocol import TrialContext, TrialExecution
from benchmarks.picobench.records import (
    DeliveryOutcome,
    TrialStatus,
    TurnTerminalState,
    VerificationState,
    VerifierResult,
)

from .models import CodeCairnMemoryTask

_PROVIDER_NAME = "deepseek"
_PROVIDER_MODEL = "deepseek-v4-flash"
_SEMANTIC_ENDPOINT = "https://api.deepseek.com"
_HARD_NEGATIVE_QUERY = "cafeteria menu typography unrelated satellite telemetry"
_MAX_PROXY_BODY_BYTES = 256 * 1024
_SEMANTIC_PROCESS_MAX_ATTEMPTS = 3
_AGENT_MAX_INPUT_TOKENS = 16_000
_AGENT_MAX_OUTPUT_TOKENS = 1_024
_SEMANTIC_MAX_INPUT_TOKENS = 8_000
_SEMANTIC_MAX_OUTPUT_TOKENS = 2_048
_TRIAL_MAX_INPUT_TOKENS = max(
    _AGENT_MAX_INPUT_TOKENS,
    _SEMANTIC_MAX_INPUT_TOKENS,
)
_TRIAL_MAX_OUTPUT_TOKENS = max(
    _AGENT_MAX_OUTPUT_TOKENS,
    _SEMANTIC_MAX_OUTPUT_TOKENS,
)
_PASSTHROUGH_ENVIRONMENT = (
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "NO_PROXY",
    "PATH",
    "TMPDIR",
    "all_proxy",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)


def _provider_call_envelope(role: str) -> tuple[int, int]:
    if role == "agent":
        return _AGENT_MAX_INPUT_TOKENS, _AGENT_MAX_OUTPUT_TOKENS
    if role == "semantic":
        return _SEMANTIC_MAX_INPUT_TOKENS, _SEMANTIC_MAX_OUTPUT_TOKENS
    raise ValueError(f"unsupported provider role: {role}")


class ProductionCodeCairnMemoryRunner:
    kind = "codecairn_memory_installed_real_provider"

    def __init__(
        self,
        *,
        config: Any,
        pico_config: Any,
        provider: Any,
        pico_wheel: Path,
        codecairn_wheel: Path,
        pair_manifest: Path,
        continuity_summary: Path,
        benchmark_source_root: Path,
    ) -> None:
        if not isinstance(provider, BudgetGuardedProvider):
            raise ValueError(
                "ProductionCodeCairnMemoryRunner requires BudgetGuardedProvider",
            )
        self._config = config
        self._pico_config = pico_config
        self._provider = provider
        self._ledger = provider.ledger
        self._pico_wheel = Path(pico_wheel).resolve()
        self._codecairn_wheel = Path(codecairn_wheel).resolve()
        self._pair_manifest = Path(pair_manifest).resolve()
        self._continuity_summary = Path(continuity_summary).resolve()
        self._benchmark_source_root = Path(
            benchmark_source_root,
        ).resolve()
        self._validate_inputs()
        self._temporary = tempfile.TemporaryDirectory(
            prefix="picobench-codecairn-production-",
        )
        self._root = Path(self._temporary.name)
        self._environment = _install_pair(
            self._root,
            pico_wheel=self._pico_wheel,
            codecairn_wheel=self._codecairn_wheel,
        )
        self._python = self._environment / "bin" / "python"
        self._codecairn = self._environment / "bin" / "codecairn"
        self._worker = self._root / "codecairn_installed_worker.py"
        shutil.copy2(
            self._benchmark_source_root / "benchmarks" / "picobench" / "codecairn_installed_worker.py",
            self._worker,
        )
        self._upstream_api_key = _provider_api_key(
            self._config,
            _PROVIDER_NAME,
        )
        self._model_cache = self._root / "model-cache"
        self._model_cache.mkdir()
        prefetch_evidence = _prefetch_codecairn_models(
            self._codecairn,
            self._root / "model-prefetch",
            self._model_cache,
        )
        identity = _worker(
            self._python,
            self._worker,
            {"worker_mode": "identity"},
            self._root / "installed-identity",
            env=_minimal_environment(
                self._root / "identity-home",
                {
                    "PICO_HOME": str(self._root / "identity-pico-home"),
                },
            ),
        )
        self.identity = {
            "codecairn_commit": _read_json(
                self._pair_manifest,
            )["audit"]["codecairn"]["commit"],
            "codecairn_wheel_sha256": _sha256(
                self._codecairn_wheel,
            ),
            "continuity_summary_sha256": _sha256(
                self._continuity_summary,
            ),
            "external_verifier_digest": _sha256(
                Path(__file__).resolve(),
            ),
            "installed_identity_digest": canonical_digest(
                identity,
            ),
            "pair_manifest_sha256": _sha256(
                self._pair_manifest,
            ),
            "pico_wheel_sha256": _sha256(self._pico_wheel),
            "retrieval_prefetch_digest": canonical_digest(
                prefetch_evidence,
            ),
            "retrieval_profile": "fastembed",
            "semantic_profile": "deepseek",
            "worker_digest": _sha256(self._worker),
        }

    async def run(self, context: TrialContext) -> TrialExecution:
        task = asyncio.create_task(
            asyncio.to_thread(self._run_sync, context),
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except BaseException:
                pass
            raise

    def _run_sync(self, context: TrialContext) -> TrialExecution:
        budget = context.experiment.execution.provider_trial_budget_for(
            context.key.pack_id,
        )
        if (
            budget is None
            or budget.max_provider_calls_per_trial != 7
            or budget.max_input_tokens_per_call != _TRIAL_MAX_INPUT_TOKENS
            or budget.max_output_tokens_per_call != _TRIAL_MAX_OUTPUT_TOKENS
        ):
            return _preparation_failure(
                context,
                "codecairn_provider_budget_not_frozen",
            )
        task = CodeCairnMemoryTask(**dict(context.task.payload))
        attempt_id = f"{task.task_id}-{context.key.variant_id}-r{context.key.repetition}-b{context.block_attempt}"
        isolation = TrialIsolation.create(
            context.experiment.output_root / ".picobench-codecairn-memory" / context.experiment_id,
            attempt_id,
        )
        isolation.prepare()
        _init_git_repository(isolation.workspace)
        _seed_local_skill(isolation.workspace)
        treatment = context.variant.settings["memory_backend"] == "codecairn"
        runtime_root = isolation.root / "codecairn-runtime"
        agent_input_tokens, agent_output_tokens = _provider_call_envelope(
            "agent",
        )
        agent_proxy_context = _MeteredSemanticProxy(
            isolation.root / "agent-proxy",
            api_key=self._upstream_api_key,
            upstream_endpoint=_SEMANTIC_ENDPOINT,
            ledger=self._ledger,
            trial_id=_trial_id(context, "agent"),
            model=_PROVIDER_MODEL,
            maximum_input_tokens=agent_input_tokens,
            maximum_output_tokens=agent_output_tokens,
            max_logical_calls=4,
            max_attempts_per_call=(context.experiment.execution.provider_call_max_attempts),
            role="agent",
        )
        semantic_proxy_context: AbstractContextManager[_MeteredSemanticProxy | None]
        semantic_input_tokens, semantic_output_tokens = _provider_call_envelope(
            "semantic",
        )
        semantic_proxy_context = (
            _MeteredSemanticProxy(
                isolation.root / "semantic-proxy",
                api_key=self._upstream_api_key,
                upstream_endpoint=_SEMANTIC_ENDPOINT,
                ledger=self._ledger,
                trial_id=_trial_id(context, "semantic"),
                model=_PROVIDER_MODEL,
                maximum_input_tokens=semantic_input_tokens,
                maximum_output_tokens=semantic_output_tokens,
                max_logical_calls=_SEMANTIC_PROCESS_MAX_ATTEMPTS,
                max_attempts_per_call=1,
                role="semantic",
            )
            if treatment
            else nullcontext(None)
        )
        ledger_before = self._ledger.snapshot()
        started = time.perf_counter()
        try:
            with (
                agent_proxy_context as agent_proxy,
                semantic_proxy_context as semantic_proxy,
            ):
                trust_bundle = isolation.root / "trust-bundle.pem"
                certificates = [agent_proxy.certificate]
                if semantic_proxy is not None:
                    certificates.append(semantic_proxy.certificate)
                _write_combined_ca_bundle(
                    tuple(certificates),
                    trust_bundle,
                )
                environment = self._trial_environment(
                    isolation,
                    semantic_proxy,
                    trust_bundle,
                )
                private_config = self._write_trial_config(
                    isolation,
                    agent_proxy,
                )
                initialization: dict[str, Any] = {}
                if treatment:
                    initialization = _initialize_codecairn(
                        self._codecairn,
                        isolation.workspace,
                        runtime_root,
                        repo_key=f"picobench/{task.task_id}",
                        environment=environment,
                    )
                learning = self._run_stage(
                    task=task,
                    isolation=isolation,
                    stage="learning",
                    prompt=task.learning_prompt,
                    conversation_id=task.prior_session_id,
                    memory_enabled=treatment,
                    environment=environment,
                    private_config=private_config,
                )
                semantic_report: dict[str, Any] = {}
                semantic_attempts: tuple[dict[str, Any], ...] = ()
                expected_ids: set[str] = set()
                learning_journal: dict[str, object] = {}
                if treatment and _clean_worker_turn(learning):
                    semantic_report, semantic_attempts = _process_semantic_with_retry(
                        self._codecairn,
                        isolation.workspace,
                        environment,
                        worker_id=f"{task.task_id}-worker",
                    )
                    (isolation.root / "semantic-process.json").write_text(
                        json.dumps(
                            semantic_report,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    (isolation.root / "semantic-process-attempts.json").write_text(
                        json.dumps(
                            {
                                "attempt_count": len(
                                    semantic_attempts,
                                ),
                                "completed": _semantic_completed(
                                    semantic_report,
                                ),
                                "reports": semantic_attempts,
                            },
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    memories = _list_memories(
                        self._codecairn,
                        isolation.workspace,
                        environment,
                    )
                    expected_ids = {
                        str(memory["memory_id"])
                        for memory in memories
                        if task.expected_value in json.dumps(memory, sort_keys=True)
                    }
                    learning_journal = _public_journal_state(
                        self._codecairn,
                        isolation.workspace,
                        _pico_source_journal(runtime_root),
                        environment,
                    )
                evaluation_prompt = (
                    task.evaluation_prompt + " Use joint_write_result exactly once with the recovered"
                    f" value and key {task.expected_key}."
                )
                evaluation = self._run_stage(
                    task=task,
                    isolation=isolation,
                    stage="evaluation",
                    prompt=evaluation_prompt,
                    conversation_id=task.evaluation_session_id,
                    memory_enabled=treatment,
                    environment=environment,
                    private_config=private_config,
                )
                negative_ids: set[str] = set()
                leakage_ids: set[str] = set()
                profile_complete = not treatment
                semantic_calls: list[dict[str, object]] = []
                if treatment:
                    negative_ids = _rendered_memory_ids(
                        _recall(
                            self._codecairn,
                            isolation.workspace,
                            _HARD_NEGATIVE_QUERY,
                            environment,
                        )
                    )
                    leakage_ids = self._cross_repository_recall(
                        task,
                        isolation,
                        environment,
                        runtime_root,
                    )
                    profile_complete = _profile_complete(
                        initialization,
                        semantic_report,
                        expected_repo_key=f"picobench/{task.task_id}",
                    )
                    semantic_calls = semantic_proxy.calls if semantic_proxy is not None else []
                    stale_evidence = _verify_stale_filter(
                        self._codecairn,
                        isolation.workspace,
                        environment,
                        task_id=task.task_id,
                    )
                else:
                    stale_evidence = {
                        "applicable": False,
                        "complete": False,
                        "stale_injection_count": None,
                    }
                agent_calls = list(agent_proxy.calls)
        except PairIntegrityError as error:
            return _preparation_failure(
                context,
                f"codecairn_trial_infrastructure:{error}",
                artifact_root=isolation.root,
            )
        elapsed_ms = (time.perf_counter() - started) * 1_000
        ledger_after = self._ledger.snapshot()
        verification = _verify_output(
            isolation.workspace,
            task,
        )
        observed_ids = _observed_memory_ids(
            isolation.root / "evaluation-recall.json",
        )
        provenance = _recall_provenance(
            isolation.root / "evaluation-recall.json",
            expected_memory_ids=expected_ids,
            expected_repo_key=f"picobench/{task.task_id}",
        )
        provenance["journal_cursor"] = (
            learning_journal.get(
                "committed_raw_event_index",
            )
            if treatment
            else None
        )
        provenance["complete"] = bool(provenance["complete"] and provenance["journal_cursor"] is not None)
        status, runtime_state, delivery_state = _trial_status(
            learning=learning,
            evaluation=evaluation,
            verification=verification,
        )
        usage = _aggregate_usage(
            learning,
            evaluation,
            semantic_calls,
        )
        worker_agent_call_count = sum(
            1 for stage in (learning, evaluation) for call in stage.get("model_calls", []) if isinstance(call, Mapping)
        )
        agent_accounting_complete = bool(agent_calls) and all(
            call.get("accounting_valid") is True for call in agent_calls
        )
        agent_calls_reconciled = len(agent_calls) == worker_agent_call_count
        actual_models = {
            str(call["model"])
            for stage in (learning, evaluation)
            for call in stage.get("model_calls", [])
            if isinstance(call, Mapping) and call.get("model") is not None
        }
        model_matches = bool(actual_models) and all(
            _normalize_model(model) == _PROVIDER_MODEL for model in actual_models
        )
        semantic_completed = not treatment or _semantic_completed(semantic_report)
        production_evidence = bool(
            treatment
            and learning.get("pid") != evaluation.get("pid")
            and evaluation.get("backend_module") == "codecairn.integrations.pico.backend"
            and profile_complete
            and semantic_completed
            and semantic_calls
            and agent_accounting_complete
            and agent_calls_reconciled
            and stale_evidence["complete"] is True
            and provenance["complete"] is True
            and provenance["repo_key"] == f"picobench/{task.task_id}"
        )
        if treatment and not semantic_completed:
            status = TrialStatus.PROVIDER_FAILURE
            verification = VerifierResult(
                state=VerificationState.NOT_RUN,
                findings=("codecairn_semantic_processing_failed",),
            )
        if treatment and not expected_ids:
            status = TrialStatus.TASK_FAILED
        relative_root = isolation.root.relative_to(
            context.experiment.output_root,
        )
        tool_metrics = _tool_metrics(
            learning,
            evaluation,
        )
        memory_off_calls = (
            int(learning.get("memory_backend_build_calls", 0)) + int(evaluation.get("memory_backend_build_calls", 0))
            if not treatment
            else None
        )
        repo_key = f"picobench/{task.task_id}"
        observed_repo_key = provenance["repo_key"] if treatment else repo_key
        return TrialExecution(
            status=status,
            runtime_state=runtime_state,
            delivery_state=delivery_state,
            verification=verification,
            observed_variant_settings=dict(
                context.variant.settings,
            ),
            metrics={
                "codecairn.memory_off_operation_calls": memory_off_calls,
                "codecairn.recall_at_5_numerator": int(bool(expected_ids & observed_ids)),
                "codecairn.recall_at_5_denominator": int(treatment),
                "codecairn.irrelevant_injections": len(
                    negative_ids,
                ),
                "codecairn.hard_negative_queries": int(treatment),
                "codecairn.stale_fixture_complete": stale_evidence["complete"],
                "codecairn.stale_evidence": stale_evidence,
                "codecairn.stale_injection_count": stale_evidence["stale_injection_count"],
                "codecairn.cross_repository_leakage_count": len(
                    leakage_ids,
                ),
                "codecairn.production_adapter": production_evidence,
                "codecairn.fresh_process": bool(
                    learning.get("pid") and evaluation.get("pid") and learning.get("pid") != evaluation.get("pid")
                ),
                "codecairn.profile_evidence_complete": (profile_complete),
                "codecairn.expected_memory_ids": sorted(
                    expected_ids,
                ),
                "codecairn.observed_memory_ids": sorted(
                    observed_ids,
                ),
                "codecairn.provenance": provenance,
                "codecairn.provenance_complete": provenance["complete"] if treatment else True,
                "codecairn.repository_identity_hash": canonical_digest(
                    {
                        "repo_key": observed_repo_key,
                    }
                ),
                "codecairn.semantic_calls": len(
                    semantic_calls,
                ),
                "codecairn.semantic_process_attempts": len(
                    semantic_attempts,
                ),
                "provider.actual_model_matches": model_matches,
                "provider.actual_models": sorted(actual_models),
                "provider.agent_accounting_complete": (agent_accounting_complete),
                "provider.agent_calls_reconciled": (agent_calls_reconciled),
                "usage.complete": usage["complete"],
                "usage.main_agent_input_tokens": usage["agent_input_tokens"],
                "usage.main_agent_output_tokens": usage["agent_output_tokens"],
                "usage.semantic_input_tokens": usage["semantic_input_tokens"],
                "usage.semantic_output_tokens": usage["semantic_output_tokens"],
                "usage.trial_total_tokens": usage["total_tokens"],
                "cost.complete": ledger_after.accounting_complete,
                "cost.estimated_cny": (ledger_after.provider_charged_cny - ledger_before.provider_charged_cny),
                "runtime.end_to_end_latency_ms": elapsed_ms,
                "runtime.memory_failures": tool_metrics["memory_failures"],
                "runtime.repeated_repository_reads": tool_metrics["repeated_repository_reads"],
                "runtime.tool_calls": tool_metrics["tool_calls"],
                "runtime.tool_failures": tool_metrics["tool_failures"],
            },
            artifact_refs=(relative_root.as_posix(),),
        )

    def _run_stage(
        self,
        *,
        task: CodeCairnMemoryTask,
        isolation: TrialIsolation,
        stage: str,
        prompt: str,
        conversation_id: str,
        memory_enabled: bool,
        environment: dict[str, str],
        private_config: Path,
    ) -> dict[str, Any]:
        return _worker(
            self._python,
            self._worker,
            {
                "conversation_id": conversation_id,
                "expected_key": task.expected_key,
                "expected_value": task.expected_value,
                "max_tokens": 1_024,
                "memory_enabled": memory_enabled,
                "message_id": f"{conversation_id}-message",
                "mode": ("learn" if stage == "learning" else "evaluate"),
                "output_file": task.output_file,
                "prompt": prompt,
                "provider": {
                    "mode": "real",
                    "private_config_path": str(
                        private_config,
                    ),
                },
                "recall_observation": str(
                    isolation.root / f"{stage}-recall.json",
                ),
                "skill_forge_enabled": True,
                "timeout_seconds": 120,
                "worker_mode": "turn",
                "workspace": str(isolation.workspace),
            },
            isolation.root / f"{stage}-worker",
            env={
                **environment,
                "PICO_HOME": str(
                    isolation.root / f"pico-home-{stage}",
                ),
                "PYTHONPATH": "",
            },
        )

    def _trial_environment(
        self,
        isolation: TrialIsolation,
        semantic_proxy: _MeteredSemanticProxy | None,
        trust_bundle: Path,
    ) -> dict[str, str]:
        environment = _minimal_environment(
            isolation.root / "worker-home",
            {
                "CODECAIRN_MODEL_CACHE": str(
                    self._model_cache,
                ),
                "PICO_TRACING_DIR": str(isolation.trace_root),
                "SSL_CERT_FILE": str(trust_bundle),
            },
        )
        if semantic_proxy is not None:
            environment.update(
                {
                    "CODECAIRN_SEMANTIC_API_KEY": (semantic_proxy.local_api_key),
                    "CODECAIRN_SEMANTIC_ENDPOINT": (semantic_proxy.endpoint),
                    "CODECAIRN_SEMANTIC_MODEL": (_PROVIDER_MODEL),
                }
            )
        return environment

    def _write_trial_config(
        self,
        isolation: TrialIsolation,
        agent_proxy: _MeteredSemanticProxy,
    ) -> Path:
        provider = getattr(
            self._config.providers,
            _PROVIDER_NAME,
        ).model_dump(mode="json")
        provider["api_key"] = agent_proxy.local_api_key
        provider["api_base"] = agent_proxy.endpoint
        path = isolation.root / "runtime-config.json"
        path.write_text(
            json.dumps(
                {
                    "config": {
                        "agents": {
                            "defaults": {
                                "model": self._config.agents.defaults.model,
                            }
                        },
                        "providers": {
                            _PROVIDER_NAME: provider,
                        },
                    },
                    "pico_config": {},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

    def _cross_repository_recall(
        self,
        task: CodeCairnMemoryTask,
        isolation: TrialIsolation,
        environment: dict[str, str],
        runtime_root: Path,
    ) -> set[str]:
        repository = isolation.root / "leakage-repository"
        _init_git_repository(repository)
        _seed_local_skill(repository)
        _initialize_codecairn(
            self._codecairn,
            repository,
            runtime_root,
            repo_key=f"picobench/leakage/{task.task_id}",
            environment=environment,
        )
        return _rendered_memory_ids(
            _recall(
                self._codecairn,
                repository,
                task.memory_query,
                environment,
            )
        )

    def _validate_inputs(self) -> None:
        for path in (
            self._pico_wheel,
            self._codecairn_wheel,
            self._pair_manifest,
            self._continuity_summary,
        ):
            if not path.is_file():
                raise ValueError(
                    f"CodeCairn campaign input is missing: {path.name}",
                )
        summary = _read_json(self._continuity_summary)
        manifest = _read_json(self._pair_manifest)
        audit = manifest.get("audit")
        current_pico = audit.get("current_pico") if isinstance(audit, Mapping) else None
        codecairn = audit.get("codecairn") if isinstance(audit, Mapping) else None
        if summary.get("passed") is not True or summary.get("paid_external_calls") != 0:
            raise ValueError(
                "CodeCairn deterministic continuity evidence is not eligible",
            )
        if (
            summary.get("pair_manifest_sha256") != _sha256(self._pair_manifest)
            or not isinstance(current_pico, Mapping)
            or current_pico.get("wheel_sha256") != _sha256(self._pico_wheel)
            or not isinstance(codecairn, Mapping)
            or codecairn.get("wheel_sha256") != _sha256(self._codecairn_wheel)
        ):
            raise ValueError(
                "CodeCairn campaign wheel pair does not match Stage A",
            )
        if not self._benchmark_source_root.is_dir():
            raise ValueError(
                "PicoBench source root is missing",
            )
        source_status = _run(
            ("git", "status", "--porcelain"),
            cwd=self._benchmark_source_root,
            env=os.environ.copy(),
        ).stdout
        source_commit = _run(
            ("git", "rev-parse", "HEAD"),
            cwd=self._benchmark_source_root,
            env=os.environ.copy(),
        ).stdout.strip()
        if source_status or not isinstance(current_pico, Mapping) or current_pico.get("commit") != source_commit:
            raise ValueError(
                "PicoBench source must be the clean Stage A Pico commit",
            )


class _MeteredSemanticProxy(
    AbstractContextManager["_MeteredSemanticProxy"],
):
    def __init__(
        self,
        root: Path,
        *,
        api_key: str,
        upstream_endpoint: str,
        ledger: ProviderBudgetLedger,
        trial_id: str,
        model: str,
        maximum_input_tokens: int,
        maximum_output_tokens: int,
        max_logical_calls: int = 1,
        max_attempts_per_call: int = 1,
        role: str = "semantic",
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.upstream_endpoint = upstream_endpoint.rstrip("/")
        self.ledger = ledger
        self.trial_id = trial_id
        self.model = model
        self.maximum_input_tokens = maximum_input_tokens
        self.maximum_output_tokens = maximum_output_tokens
        self.max_logical_calls = max_logical_calls
        self.max_attempts_per_call = max_attempts_per_call
        self.role = role
        self.local_api_key = secrets.token_urlsafe(32)
        self.certificate = self.root / "certificate.pem"
        self.trust_bundle = self.root / "trust-bundle.pem"
        self._key = self.root / "key.pem"
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.calls: list[dict[str, object]] = []

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise RuntimeError(
                "semantic proxy is not running",
            )
        return f"https://localhost:{self._server.server_port}/v1"

    def __enter__(self) -> _MeteredSemanticProxy:
        openssl = shutil.which("openssl")
        if openssl is None:
            raise PairIntegrityError(
                "openssl is required for the semantic proxy",
            )
        _run(
            (
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(self._key),
                "-out",
                str(self.certificate),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ),
            cwd=self.root,
            env=os.environ.copy(),
        )
        _write_combined_ca_bundle(
            self.certificate,
            self.trust_bundle,
        )
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if (
                    self.path != "/v1/chat/completions"
                    or self.headers.get("Authorization") != f"Bearer {owner.local_api_key}"
                ):
                    self.send_error(404)
                    return
                try:
                    content_length = int(
                        self.headers.get(
                            "Content-Length",
                            "0",
                        )
                    )
                except ValueError:
                    self.send_error(400)
                    return
                if content_length <= 0 or content_length > _MAX_PROXY_BODY_BYTES:
                    self.send_error(413)
                    return
                raw = self.rfile.read(content_length)
                if len(raw) != content_length:
                    self.send_error(400)
                    return
                owner._forward(self, raw)

            def log_message(
                self,
                format: str,
                *args: object,
            ) -> None:
                del format, args

        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            Handler,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            self.certificate,
            self._key,
        )
        server.socket = context.wrap_socket(
            server.socket,
            server_side=True,
        )
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _forward(
        self,
        handler: http.server.BaseHTTPRequestHandler,
        raw: bytes,
    ) -> None:
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            handler.send_error(400)
            return
        if (
            not isinstance(request, dict)
            or not isinstance(request.get("messages"), list)
            or (request.get("tools") is not None and not isinstance(request.get("tools"), list))
            or request.get("stream") not in (None, False)
        ):
            handler.send_error(400)
            return
        request["model"] = self.model
        request["max_tokens"] = self.maximum_output_tokens
        request["stream"] = False
        estimated_input = _conservative_serialized_input_tokens(
            request["messages"],
            request.get("tools"),
            model=self.model,
            max_tokens=self.maximum_output_tokens,
            temperature=float(request.get("temperature", 0.0)),
            reasoning_effort=request.get("reasoning_effort"),
            tool_choice=request.get("tool_choice"),
        )
        if estimated_input > self.maximum_input_tokens:
            self._send_context_overflow(handler)
            return
        normalized_request = json.dumps(
            request,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        try:
            request_id = self.ledger.reserve(
                trial_id=self.trial_id,
                request_digest=hashlib.sha256(
                    normalized_request,
                ).hexdigest(),
                model=self.model,
                estimated_input_tokens=estimated_input,
                maximum_input_tokens=self.maximum_input_tokens,
                maximum_output_tokens=self.maximum_output_tokens,
                max_logical_calls=self.max_logical_calls,
                max_attempts_per_call=self.max_attempts_per_call,
            )
        except Exception:
            handler.send_error(429)
            return
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.upstream_endpoint}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request,
                timeout=60,
            )
            body = response.content
            payload = response.json()
            usage = payload.get("usage") if isinstance(payload, dict) else None
            input_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
            output_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
            total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            returned_model = payload.get("model") if isinstance(payload, dict) else None
            accounting_valid = bool(
                response.is_success
                and all(
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in (
                        input_tokens,
                        output_tokens,
                        total_tokens,
                    )
                )
                and total_tokens == input_tokens + output_tokens
                and isinstance(returned_model, str)
                and _normalize_model(returned_model) == self.model
            )
            if accounting_valid:
                self.ledger.settle(
                    request_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            else:
                self.ledger.fail(
                    request_id,
                    reason=(
                        f"{self.role}_http_{response.status_code}"
                        if not response.is_success
                        else f"{self.role}_usage_or_model_invalid"
                    ),
                )
        except BaseException as error:
            self.ledger.fail(
                request_id,
                reason=(f"{self.role}_provider_exception:{type(error).__name__}"),
            )
            handler.send_error(502)
            return
        self.calls.append(
            {
                "accounting_valid": accounting_valid,
                "input_tokens": input_tokens,
                "latency_ms": (time.perf_counter() - started) * 1_000,
                "model": returned_model,
                "output_tokens": output_tokens,
                "status_code": response.status_code,
            }
        )
        if not accounting_valid:
            handler.send_error(502)
            return
        handler.send_response(response.status_code)
        handler.send_header(
            "Content-Type",
            response.headers.get(
                "Content-Type",
                "application/json",
            ),
        )
        handler.send_header(
            "Content-Length",
            str(len(body)),
        )
        handler.end_headers()
        handler.wfile.write(body)

    @staticmethod
    def _send_context_overflow(
        handler: http.server.BaseHTTPRequestHandler,
    ) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "context_length_exceeded",
                    "message": ("Request exceeds the maximum context length; reduce the length of the messages."),
                    "param": "messages",
                    "type": "invalid_request_error",
                }
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        handler.send_response(413)
        handler.send_header(
            "Content-Type",
            "application/json",
        )
        handler.send_header(
            "Content-Length",
            str(len(body)),
        )
        handler.end_headers()
        handler.wfile.write(body)


def _minimal_environment(
    home: Path,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    environment = {name: os.environ[name] for name in _PASSTHROUGH_ENVIRONMENT if os.environ.get(name)}
    environment.update(
        {
            "HOME": str(home),
            "PYTHONPATH": "",
        }
    )
    no_proxy = {
        value.strip()
        for name in ("NO_PROXY", "no_proxy")
        for value in environment.get(name, "").split(",")
        if value.strip()
    }
    no_proxy.update({"127.0.0.1", "localhost"})
    encoded_no_proxy = ",".join(sorted(no_proxy))
    environment["NO_PROXY"] = encoded_no_proxy
    environment["no_proxy"] = encoded_no_proxy
    if extra is not None:
        environment.update({str(name): str(value) for name, value in extra.items()})
    return environment


def _write_combined_ca_bundle(
    local_certificates: Path | tuple[Path, ...],
    output: Path,
) -> None:
    public_bundle = Path(certifi.where()).read_bytes()
    certificates = (local_certificates,) if isinstance(local_certificates, Path) else local_certificates
    if not certificates:
        raise ValueError("at least one local certificate is required")
    local_bundle = b"\n".join(certificate.read_bytes().strip() for certificate in certificates)
    output.write_bytes(
        public_bundle.rstrip() + b"\n" + local_bundle + b"\n",
    )
    output.chmod(0o600)


def _verify_stale_filter(
    executable: Path,
    workspace: Path,
    environment: dict[str, str],
    *,
    task_id: str,
) -> dict[str, object]:
    subject = f"stale-probe-{task_id}"
    query = f"{subject} current replacement"
    predecessor = _command_json(
        (
            str(executable),
            "remember",
            "repository_knowledge",
            f"{subject} obsolete predecessor",
            "--subject-key",
            subject,
            "--title",
            "Stale predecessor",
        ),
        cwd=workspace,
        env=environment,
    )
    successor = _command_json(
        (
            str(executable),
            "remember",
            "repository_knowledge",
            f"{subject} current replacement",
            "--subject-key",
            subject,
            "--title",
            "Current successor",
        ),
        cwd=workspace,
        env=environment,
    )
    predecessor_id = predecessor.get("memory_id")
    successor_id = successor.get("memory_id")
    if not isinstance(predecessor_id, str) or not isinstance(successor_id, str):
        raise PairIntegrityError(
            "stale fixture did not create durable Memory identities",
        )
    _command_json(
        (
            str(executable),
            "memory",
            "supersede",
            predecessor_id,
            successor_id,
            "--reason",
            "PicoBench stale filtering fixture",
        ),
        cwd=workspace,
        env=environment,
    )
    process = _command_json(
        (
            str(executable),
            "process",
            "--no-semantic",
            "--worker-id",
            f"{task_id}-stale-index",
            "--max-jobs",
            "8",
        ),
        cwd=workspace,
        env=environment,
    )
    rendered = _rendered_memory_ids(
        _recall(
            executable,
            workspace,
            query,
            environment,
        )
    )
    index = process.get("index")
    index_ready = bool(
        isinstance(index, Mapping)
        and index.get("pending") == 0
        and index.get("leased") == 0
        and index.get("failed") == 0
        and index.get("stale") == 0
    )
    stale_injection_count = int(predecessor_id in rendered)
    complete = bool(index_ready and successor_id in rendered and stale_injection_count == 0)
    return {
        "complete": complete,
        "predecessor_id": predecessor_id,
        "rendered_memory_ids": sorted(rendered),
        "stale_injection_count": stale_injection_count,
        "successor_id": successor_id,
    }


def _recall_provenance(
    path: Path,
    *,
    expected_memory_ids: set[str],
    expected_repo_key: str,
) -> dict[str, object]:
    if not path.is_file():
        return {
            "complete": False,
            "index_cursor": None,
            "observed_expected_memory_ids": [],
            "repo_key": None,
            "source_cursor": None,
            "source_uris": [],
        }
    observation = _read_json(path)
    hits = observation.get("hits")
    metadata: list[Mapping[str, Any]] = []
    observed_expected_ids: set[str] = set()
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, Mapping):
            continue
        item = hit.get("metadata")
        if not isinstance(item, Mapping):
            continue
        rendered = {
            str(memory_id)
            for memory_id in _string_sequence(
                item.get("rendered_memory_ids"),
            )
            if isinstance(memory_id, str)
        }
        overlap = rendered & expected_memory_ids
        if overlap:
            metadata.append(item)
            observed_expected_ids.update(overlap)
    source_uris = sorted(
        {
            uri
            for item in metadata
            for uri in _string_sequence(
                item.get("source_uris"),
            )
            if uri
        }
    )
    source_cursors = {item.get("source_cursor") for item in metadata if item.get("source_cursor") is not None}
    index_cursors = {item.get("index_cursor") for item in metadata if item.get("index_cursor") is not None}
    provenance_per_hit = all(
        item.get("repo_key") == expected_repo_key
        and bool(_string_sequence(item.get("source_uris")))
        and item.get("source_cursor") is not None
        and item.get("index_cursor") is not None
        for item in metadata
    )
    complete = bool(
        expected_memory_ids
        and observed_expected_ids
        and metadata
        and provenance_per_hit
        and len(source_cursors) == 1
        and len(index_cursors) == 1
    )
    return {
        "complete": complete,
        "index_cursor": (next(iter(index_cursors)) if len(index_cursors) == 1 else None),
        "observed_expected_memory_ids": sorted(
            observed_expected_ids,
        ),
        "repo_key": expected_repo_key if complete else None,
        "source_cursor": (next(iter(source_cursors)) if len(source_cursors) == 1 else None),
        "source_uris": source_uris,
    }


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _tool_metrics(
    learning: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> dict[str, int]:
    starts = [
        event
        for stage in (learning, evaluation)
        for event in stage.get("tool_events", [])
        if isinstance(event, Mapping) and event.get("phase") == "start"
    ]
    read_keys = [
        (
            str(event.get("name")),
            json.dumps(
                event.get("arguments") or {},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        for event in starts
        if event.get("name")
        in {
            "read_file",
            "grep",
            "find",
            "list_dir",
        }
    ]
    repeated_reads = len(read_keys) - len(set(read_keys))
    memory_failures = sum(
        int(
            stage.get("close_error") is not None
            or (
                isinstance(stage.get("turn_error"), Mapping)
                and "memory"
                in str(
                    stage["turn_error"].get(
                        "category",
                        "",
                    )
                ).lower()
            )
        )
        for stage in (learning, evaluation)
    )
    return {
        "memory_failures": memory_failures,
        "repeated_repository_reads": repeated_reads,
        "tool_calls": len(starts),
        "tool_failures": sum(
            int(event.get("failed") is True)
            for stage in (learning, evaluation)
            for event in stage.get("tool_events", [])
            if isinstance(event, Mapping) and event.get("phase") == "complete"
        ),
    }


def _initialize_codecairn(
    executable: Path,
    repository: Path,
    runtime_root: Path,
    *,
    repo_key: str,
    environment: dict[str, str],
) -> dict[str, Any]:
    value = _command_json(
        (
            str(executable),
            "init",
            "--root",
            str(runtime_root),
            "--repo-key",
            repo_key,
            "--retrieval-profile",
            "fastembed",
            "--semantic-profile",
            "deepseek",
            "--prefetch",
        ),
        cwd=repository,
        env=environment,
    )
    if not isinstance(value, Mapping):
        raise PairIntegrityError(
            "codecairn init returned an invalid payload",
        )
    return dict(value)


def _prefetch_codecairn_models(
    executable: Path,
    root: Path,
    model_cache: Path,
) -> dict[str, object]:
    repository = root / "repository"
    runtime_root = root / "runtime"
    _init_git_repository(repository)
    try:
        report = _initialize_codecairn(
            executable,
            repository,
            runtime_root,
            repo_key="picobench/model-prefetch",
            environment=_minimal_environment(
                root / "home",
                {
                    "CODECAIRN_MODEL_CACHE": str(model_cache),
                    "CODECAIRN_SEMANTIC_ENDPOINT": _SEMANTIC_ENDPOINT,
                    "CODECAIRN_SEMANTIC_MODEL": _PROVIDER_MODEL,
                },
            ),
        )
    except subprocess.TimeoutExpired as error:
        raise PairIntegrityError(
            "codecairn retrieval model prefetch timed out",
        ) from error
    provider_state = report.get("provider_state")
    if (
        not isinstance(provider_state, Mapping)
        or provider_state.get("retrieval") != "fastembed"
        or provider_state.get("retrieval_state") != "live_verified"
    ):
        raise PairIntegrityError(
            "codecairn retrieval model prefetch was not live verified",
        )
    return {
        "retrieval": provider_state["retrieval"],
        "retrieval_state": provider_state["retrieval_state"],
    }


def _seed_local_skill(repository: Path) -> None:
    (repository / "TOOLS.md").write_text(
        "# PicoBench Tool Policy\n\n"
        "- For a learning request, acknowledge the fact without calling any tool.\n"
        "- For an evaluation request, use recalled Memory and call "
        "`joint_write_result` exactly once only when the exact value is present.\n"
        "- Do not call read_file, grep, find, list_dir, or any other unavailable tool.\n"
        "- If the exact value is absent, do not guess and do not call the result tool.\n"
        "- After a successful result tool call, reply with one short sentence.\n",
        encoding="utf-8",
    )
    skill = repository / "skills" / "memory-evaluation" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: memory-evaluation\n"
        "description: Persist one recalled repository fact.\n---\n"
        "On a learning request, acknowledge the fact without tools. "
        "On an evaluation request, use only the dedicated result tool "
        "when the exact recalled value is present; otherwise do not guess.\n",
        encoding="utf-8",
    )


def _profile_complete(
    initialization: Mapping[str, Any],
    process_report: Mapping[str, Any],
    *,
    expected_repo_key: str,
) -> bool:
    binding_value = initialization.get("config")
    if not isinstance(binding_value, str) or not binding_value:
        return False
    binding = Path(binding_value)
    try:
        payload = tomllib.loads(
            binding.read_text(encoding="utf-8"),
        )
    except (OSError, tomllib.TOMLDecodeError):
        return False
    retrieval = payload.get("retrieval")
    semantic = payload.get("semantic")
    return bool(
        isinstance(retrieval, Mapping)
        and retrieval.get("profile") == "fastembed"
        and isinstance(semantic, Mapping)
        and semantic.get("profile") == "deepseek"
        and initialization.get("repo_key") == expected_repo_key
        and initialization.get("semantic") == "deepseek"
        and isinstance(initialization.get("retrieval"), Mapping)
        and initialization["retrieval"].get("profile") == "fastembed"
        and _semantic_completed(process_report)
    )


def _semantic_completed(
    report: Mapping[str, Any],
) -> bool:
    semantic = report.get("semantic")
    return bool(
        isinstance(semantic, Mapping)
        and semantic.get("completed") == 1
        and semantic.get("failed") == 0
        and semantic.get("pending") == 0
    )


def _process_semantic_with_retry(
    executable: Path,
    workspace: Path,
    environment: dict[str, str],
    *,
    worker_id: str,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(_SEMANTIC_PROCESS_MAX_ATTEMPTS):
        command = [
            str(executable),
            "process",
            "--worker-id",
            worker_id,
            "--max-jobs",
            "8",
        ]
        if attempt:
            command.append(
                "--retry-failed",
            )
        value = _command_json(
            tuple(command),
            cwd=workspace,
            env=environment,
        )
        if not isinstance(value, Mapping):
            raise PairIntegrityError(
                "codecairn process returned an invalid payload",
            )
        report = dict(value)
        attempts.append(report)
        if _semantic_completed(report):
            break
    return attempts[-1], tuple(attempts)


def _list_memories(
    executable: Path,
    workspace: Path,
    environment: dict[str, str],
) -> list[dict[str, Any]]:
    value = _command_json(
        (str(executable), "list"),
        cwd=workspace,
        env=environment,
    )
    if not isinstance(value, list):
        raise PairIntegrityError(
            "codecairn list returned an invalid payload",
        )
    return [item for item in value if isinstance(item, dict)]


def _recall(
    executable: Path,
    workspace: Path,
    query: str,
    environment: dict[str, str],
) -> dict[str, Any]:
    value = _command_json(
        (
            str(executable),
            "recall",
            query,
            "--limit",
            "5",
            "--format",
            "json",
        ),
        cwd=workspace,
        env=environment,
    )
    if not isinstance(value, dict):
        raise PairIntegrityError(
            "codecairn recall returned an invalid payload",
        )
    return value


def _rendered_memory_ids(
    recall: Mapping[str, Any],
) -> set[str]:
    sidecar = recall.get("sidecar")
    if not isinstance(sidecar, Mapping):
        return set()
    context_trace = sidecar.get("context_trace")
    if not isinstance(context_trace, Mapping):
        return set()
    values = context_trace.get("rendered_memory_ids", ())
    if not isinstance(values, list | tuple):
        return set()
    return {str(value) for value in values if isinstance(value, str)}


def _observed_memory_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    observation = _read_json(path)
    return {
        str(memory_id)
        for hit in observation.get("hits", [])
        if isinstance(hit, Mapping)
        for memory_id in (
            hit.get("metadata", {}).get(
                "rendered_memory_ids",
                [],
            )
            if isinstance(hit.get("metadata"), Mapping)
            else []
        )
        if isinstance(memory_id, str)
    }


def _verify_output(
    workspace: Path,
    task: CodeCairnMemoryTask,
) -> VerifierResult:
    output = workspace / task.output_file
    try:
        value = json.loads(
            output.read_text(encoding="utf-8"),
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return VerifierResult(
            state=VerificationState.FAILED,
            findings=("result_artifact_missing_or_invalid",),
        )
    passed = value == {
        task.expected_key: task.expected_value,
    }
    return VerifierResult(
        state=(VerificationState.PASSED if passed else VerificationState.FAILED),
        findings=(() if passed else ("result_artifact_value_mismatch",)),
        metrics={
            "verifier_schema": ("pico.picobench.codecairn-result.v1"),
        },
    )


def _trial_status(
    *,
    learning: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    verification: VerifierResult,
) -> tuple[
    TrialStatus,
    TurnTerminalState | None,
    DeliveryOutcome | None,
]:
    if not _clean_worker_turn(learning):
        state = _runtime_state(learning)
        return (
            (
                TrialStatus.PROVIDER_FAILURE
                if state is TurnTerminalState.PROVIDER_FAILED
                else TrialStatus.INFRASTRUCTURE_FAILURE
            ),
            state,
            _delivery_state(learning),
        )
    runtime_state = _runtime_state(evaluation)
    delivery_state = _delivery_state(evaluation)
    if runtime_state is TurnTerminalState.PROVIDER_FAILED:
        status = TrialStatus.PROVIDER_FAILURE
    elif runtime_state not in {
        TurnTerminalState.COMPLETED,
        TurnTerminalState.COMPLETED_WITH_TOOL_FAILURE,
    }:
        status = TrialStatus.TASK_FAILED
    elif verification.state is VerificationState.PASSED:
        status = TrialStatus.PASSED
    else:
        status = TrialStatus.TASK_FAILED
    return status, runtime_state, delivery_state


def _runtime_state(
    stage: Mapping[str, Any],
) -> TurnTerminalState | None:
    turn_error = stage.get("turn_error")
    if isinstance(turn_error, Mapping) and turn_error.get("type") == "ProviderTurnError":
        return TurnTerminalState.PROVIDER_FAILED
    terminal_error = stage.get("terminal_error")
    if isinstance(terminal_error, str) and terminal_error.startswith(
        "provider_error:",
    ):
        return TurnTerminalState.PROVIDER_FAILED
    outcome = stage.get("outcome")
    if not isinstance(outcome, Mapping):
        return None
    value = outcome.get("status")
    if value == "completed":
        return TurnTerminalState.COMPLETED
    if value == "cancelled":
        return TurnTerminalState.CANCELLED
    if value == "failed":
        return TurnTerminalState.ERROR
    return None


def _delivery_state(
    stage: Mapping[str, Any],
) -> DeliveryOutcome | None:
    return DeliveryOutcome.DELIVERED if stage.get("delivery_events") else DeliveryOutcome.NO_OUTLET


def _clean_worker_turn(
    stage: Mapping[str, Any],
) -> bool:
    outcome = stage.get("outcome")
    return bool(
        stage.get("terminal") == "completed"
        and stage.get("close_error") is None
        and isinstance(outcome, Mapping)
        and outcome.get("status") == "completed"
    )


def _aggregate_usage(
    learning: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    semantic_calls: list[dict[str, object]],
) -> dict[str, int | bool]:
    agent_calls = [
        call for stage in (learning, evaluation) for call in stage.get("model_calls", []) if isinstance(call, Mapping)
    ]
    agent_usage = [call.get("usage") for call in agent_calls if isinstance(call.get("usage"), Mapping)]
    agent_complete = (
        bool(agent_calls)
        and len(agent_usage) == len(agent_calls)
        and all(_usage_is_complete(usage) for usage in agent_usage)
    )
    agent_input = sum(int(usage["prompt_tokens"]) for usage in agent_usage if _usage_is_complete(usage))
    agent_output = sum(int(usage["completion_tokens"]) for usage in agent_usage if _usage_is_complete(usage))
    semantic_complete = all(
        call.get("accounting_valid") is True
        and _nonnegative_integer(call.get("input_tokens"))
        and _nonnegative_integer(call.get("output_tokens"))
        for call in semantic_calls
    )
    semantic_input = sum(
        int(call["input_tokens"]) for call in semantic_calls if _nonnegative_integer(call.get("input_tokens"))
    )
    semantic_output = sum(
        int(call["output_tokens"]) for call in semantic_calls if _nonnegative_integer(call.get("output_tokens"))
    )
    return {
        "agent_input_tokens": agent_input,
        "agent_output_tokens": agent_output,
        "complete": agent_complete and semantic_complete,
        "semantic_input_tokens": semantic_input,
        "semantic_output_tokens": semantic_output,
        "total_tokens": (agent_input + agent_output + semantic_input + semantic_output),
    }


def _usage_is_complete(
    usage: Mapping[str, Any],
) -> bool:
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    return bool(
        _nonnegative_integer(prompt)
        and _nonnegative_integer(completion)
        and _nonnegative_integer(total)
        and total == prompt + completion
    )


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _normalize_model(model: str) -> str:
    return model.removeprefix(f"{_PROVIDER_NAME}/")


def _provider_api_key(
    config: Any,
    provider_name: str,
) -> str:
    provider = getattr(config.providers, provider_name)
    value = provider.api_key
    getter = getattr(value, "get_secret_value", None)
    key = getter() if callable(getter) else str(value or "")
    if not key:
        raise ValueError(
            "DeepSeek Provider credential is missing",
        )
    return key


def _trial_id(
    context: TrialContext,
    role: str,
) -> str:
    return (
        f"{context.experiment_id}/{context.key.pack_id}/"
        f"{context.key.task_id}/{context.key.variant_id}/"
        f"{context.key.repetition}/{context.block_attempt}/"
        f"{role}"
    )


def _preparation_failure(
    context: TrialContext,
    finding: str,
    *,
    artifact_root: Path | None = None,
) -> TrialExecution:
    refs: tuple[str, ...] = ()
    if artifact_root is not None:
        refs = (
            artifact_root.relative_to(
                context.experiment.output_root,
            ).as_posix(),
        )
    return TrialExecution(
        status=TrialStatus.INFRASTRUCTURE_FAILURE,
        runtime_state=None,
        delivery_state=None,
        verification=VerifierResult(
            state=VerificationState.NOT_RUN,
            findings=(finding,),
        ),
        observed_variant_settings=dict(
            context.variant.settings,
        ),
        metrics={
            "codecairn.memory_off_operation_calls": None,
            "codecairn.production_adapter": False,
            "codecairn.fresh_process": False,
            "codecairn.profile_evidence_complete": False,
            "provider.actual_model_matches": False,
            "usage.complete": False,
            "cost.complete": False,
        },
        findings=(finding,),
        artifact_refs=refs,
    )


__all__ = ["ProductionCodeCairnMemoryRunner"]
