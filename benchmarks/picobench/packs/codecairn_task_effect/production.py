from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from benchmarks.picobench.budget import BudgetGuardedProvider
from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.codecairn_continuity import (
    PairIntegrityError,
    _command_json,
    _init_git_repository,
    _install_pair,
    _read_json,
    _run,
    _sha256,
    _worker,
)
from benchmarks.picobench.protocol import (
    RetrievalContext,
    RetrievalExecution,
    TrialContext,
    TrialExecution,
)
from benchmarks.picobench.records import (
    DeliveryOutcome,
    RetrievalStatus,
    TrialStatus,
    TurnTerminalState,
    VerificationState,
    VerifierResult,
)

from ..codecairn_memory.production import (
    _MeteredSemanticProxy,
    _minimal_environment,
    _prefetch_codecairn_models,
    _provider_api_key,
    _write_combined_ca_bundle,
)
from .definitions import (
    load_retrieval_definition,
    load_task_effect_tasks,
)
from .fixtures import (
    FIXTURE_MARKER,
    FIXTURE_MARKER_SCHEMA,
    build_parent_owned_prior_fixture,
    build_repository_fixture,
    fixture_file_drift,
    observed_repository_paths,
)
from .models import (
    MemoryValidity,
    RetrievalDefinition,
    RetrievalMemory,
    RetrievalQuery,
    RetrievalQueryClass,
    TaskClass,
    TaskDefinitionKind,
    TaskEffectTask,
    TaskEffectVerificationEvidence,
)
from .runner import (
    _PACK_IDS,
    _attempt_workspace_path,
    _reset_attempt_workspace,
    _run_repository_check,
)
from .verifier import SealedTaskEffectVerifier

_PROVIDER_NAME = "deepseek"
_PROVIDER_MODEL = "deepseek-v4-flash"
_PROVIDER_ENDPOINT = "https://api.deepseek.com"
_RUNNER_KIND = "codecairn_task_effect_installed_real_provider"
_ATTESTATION_SCHEMA = "pico.picobench.task-effect-production-adapter.v1"
_STAGE_C_SCHEMA = "pico.picobench.codecairn-task-effect-stage-c.v1"
_MAX_PROVIDER_CALLS_PER_TRIAL = 9
_MAX_INPUT_TOKENS_PER_CALL = 16_000
_MAX_OUTPUT_TOKENS_PER_CALL = 2_048
_RUNTIME_OWNED_PATHS = (
    PurePosixPath(".git"),
    PurePosixPath("memory/.curator"),
)


class ProductionTaskEffectRunner:
    kind = _RUNNER_KIND

    def __init__(
        self,
        *,
        config: Any,
        pico_config: Any,
        provider: Any,
        pico_wheel: Path,
        codecairn_wheel: Path,
        stage_c_summary: Path,
        benchmark_source_root: Path,
    ) -> None:
        if not isinstance(provider, BudgetGuardedProvider):
            raise ValueError(
                "ProductionTaskEffectRunner requires BudgetGuardedProvider",
            )
        self._config = config
        self._pico_config = pico_config
        self._provider = provider
        self._ledger = provider.ledger
        self._pico_wheel = Path(pico_wheel).resolve()
        self._codecairn_wheel = Path(codecairn_wheel).resolve()
        self._stage_c_summary = Path(stage_c_summary).resolve()
        self._benchmark_source_root = Path(
            benchmark_source_root,
        ).resolve()
        stage_c = self._validate_inputs()
        self._temporary = tempfile.TemporaryDirectory(
            prefix="picobench-task-effect-v2-",
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
        prefetch = _prefetch_codecairn_models(
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
                    "PICO_HOME": str(
                        self._root / "identity-pico-home",
                    ),
                },
            ),
        )
        implementation_digest = _sha256(Path(__file__).resolve())
        self.identity = {
            "codecairn_commit": stage_c["codecairn"]["commit"],
            "codecairn_wheel_sha256": _sha256(
                self._codecairn_wheel,
            ),
            "installed_identity_digest": canonical_digest(
                identity,
            ),
            "paid_external_calls_before_campaign": 0,
            "pico_commit": stage_c["pico"]["commit"],
            "pico_wheel_sha256": _sha256(self._pico_wheel),
            "production_adapter_attestation": {
                "schema": _ATTESTATION_SCHEMA,
                "adapter_id": self.kind,
                "adapter_digest": implementation_digest,
            },
            "production_evidence_complete": True,
            "retrieval_prefetch_digest": canonical_digest(
                prefetch,
            ),
            "retrieval_profile": "fastembed",
            "semantic_profile": "none",
            "stage_c_summary_sha256": _sha256(
                self._stage_c_summary,
            ),
            "worker_digest": _sha256(self._worker),
        }
        self._tasks = {task.task_id: task for kind in TaskDefinitionKind for task in load_task_effect_tasks(kind)}
        self._retrieval = {
            query.query_id: (definition, query)
            for kind in TaskDefinitionKind
            for definition in (load_retrieval_definition(kind),)
            for query in definition.queries
        }
        self._retrieval_stores: dict[
            TaskDefinitionKind,
            _RetrievalStore,
        ] = {}
        self._retrieval_lock = threading.Lock()

    async def run_trial(
        self,
        context: TrialContext,
    ) -> TrialExecution:
        task = asyncio.create_task(
            asyncio.to_thread(
                self._run_trial_sync,
                context,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except BaseException:
                pass
            raise

    async def run_retrieval_case(
        self,
        context: RetrievalContext,
    ) -> RetrievalExecution:
        task = asyncio.create_task(
            asyncio.to_thread(
                self._run_retrieval_sync,
                context,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except BaseException:
                pass
            raise

    def _run_trial_sync(
        self,
        context: TrialContext,
    ) -> TrialExecution:
        task = self._tasks.get(context.task.task_id)
        if (
            task is None
            or context.key.task_id != context.task.task_id
            or context.key.pack_id != _PACK_IDS[task.definition_kind]
        ):
            return _trial_failure(
                context,
                "task_effect_production_definition_mismatch",
            )
        budget = context.experiment.execution.provider_trial_budget_for(
            context.key.pack_id,
        )
        if (
            budget is None
            or budget.max_provider_calls_per_trial != _MAX_PROVIDER_CALLS_PER_TRIAL
            or budget.max_input_tokens_per_call != _MAX_INPUT_TOKENS_PER_CALL
            or budget.max_output_tokens_per_call != _MAX_OUTPUT_TOKENS_PER_CALL
        ):
            return _trial_failure(
                context,
                "task_effect_provider_budget_not_frozen",
            )
        treatment = context.variant.settings.get("memory_backend") == "codecairn"
        if treatment != (context.variant.variant_id == "codecairn"):
            return _trial_failure(
                context,
                "task_effect_variant_contract_mismatch",
            )
        try:
            return self._execute_trial(
                context,
                task,
                treatment=treatment,
            )
        except (
            OSError,
            PairIntegrityError,
            TypeError,
            ValueError,
        ) as error:
            return _trial_failure(
                context,
                "task_effect_production_setup_failed:" + type(error).__name__,
            )

    def _execute_trial(
        self,
        context: TrialContext,
        task: TaskEffectTask,
        *,
        treatment: bool,
    ) -> TrialExecution:
        output_root = Path(
            context.experiment.output_root,
        ).resolve()
        experiment_root, workspace = _attempt_workspace_path(
            output_root=output_root,
            experiment_id=context.experiment_id,
            pack_id=context.key.pack_id,
            task_id=task.task_id,
            repetition=context.key.repetition,
            variant_id=context.key.variant_id,
            block_attempt=context.block_attempt,
        )
        workspace.parent.mkdir(parents=True, exist_ok=True)
        _reset_attempt_workspace(
            task,
            workspace,
            experiment_root=experiment_root,
        )
        parent_owned_setup = self._prepare_workspace(
            task,
            workspace,
        )
        before = _file_digests(workspace)
        _init_git_repository(workspace)
        isolation_root = workspace.parent
        runtime_root = isolation_root / "codecairn-runtime"
        environment = _minimal_environment(
            isolation_root / "worker-home",
            {
                "CODECAIRN_MODEL_CACHE": str(
                    self._model_cache,
                ),
                "PICO_TRACING_DIR": str(
                    isolation_root / "traces",
                ),
            },
        )
        memory_receipt: dict[str, Any] = {
            "active_memory_ids": [],
            "expected_repo_key": task.fixture.repository_id,
            "seeded": False,
            "superseded_memory_ids": [],
        }
        if treatment:
            self._initialize_codecairn(
                workspace,
                runtime_root,
                task.fixture.repository_id,
                environment,
            )
            memory_receipt = self._seed_task_memory(
                task,
                workspace,
                runtime_root,
                environment,
            )
        ledger_before = self._ledger.snapshot()
        started = time.perf_counter()
        with _MeteredSemanticProxy(
            isolation_root / "agent-proxy",
            api_key=self._upstream_api_key,
            upstream_endpoint=_PROVIDER_ENDPOINT,
            ledger=self._ledger,
            trial_id=_trial_id(context),
            model=_PROVIDER_MODEL,
            maximum_input_tokens=(_MAX_INPUT_TOKENS_PER_CALL),
            maximum_output_tokens=(_MAX_OUTPUT_TOKENS_PER_CALL),
            max_logical_calls=(_MAX_PROVIDER_CALLS_PER_TRIAL),
            max_attempts_per_call=(context.experiment.execution.provider_call_max_attempts),
            role="agent",
        ) as agent_proxy:
            trust_bundle = isolation_root / "trust-bundle.pem"
            _write_combined_ca_bundle(
                agent_proxy.certificate,
                trust_bundle,
            )
            environment.update(
                {
                    "SSL_CERT_FILE": str(trust_bundle),
                    "PICO_HOME": str(
                        isolation_root / "pico-home",
                    ),
                }
            )
            private_config = self._write_trial_config(
                isolation_root,
                agent_proxy,
            )
            worker_result = _worker(
                self._python,
                self._worker,
                {
                    "conversation_id": (f"{task.task_id}-{context.key.variant_id}"),
                    "expected_key": task.expected_id,
                    "expected_value": "",
                    "context_window_tokens": (_MAX_INPUT_TOKENS_PER_CALL + _MAX_OUTPUT_TOKENS_PER_CALL),
                    "max_tokens": (_MAX_OUTPUT_TOKENS_PER_CALL),
                    "max_tool_iterations": 8,
                    "memory_enabled": treatment,
                    "message_id": (f"{task.task_id}-{context.key.repetition}-{context.block_attempt}"),
                    "mode": "task_effect",
                    "output_file": task.artifact_path,
                    "prompt": _task_prompt(task),
                    "provider": {
                        "mode": "real",
                        "private_config_path": str(
                            private_config,
                        ),
                    },
                    "recall_observation": str(isolation_root / "evaluation-recall.json"),
                    "skill_forge_enabled": False,
                    "timeout_seconds": min(
                        180,
                        context.experiment.execution.timeout_seconds,
                    ),
                    "worker_mode": "turn",
                    "workspace": str(workspace),
                },
                isolation_root / "worker",
                env=environment,
            )
            proxy_calls = tuple(agent_proxy.calls)
        elapsed_ms = (time.perf_counter() - started) * 1_000
        ledger_after = self._ledger.snapshot()
        _remove_runtime_paths(workspace)
        after = _file_digests(workspace)
        changed_paths = tuple(sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path)))
        tool_metrics = _tool_receipts(
            worker_result.get("tool_events"),
        )
        test_state = asyncio.run(
            _run_repository_check(
                task,
                workspace,
            )
        )
        evidence = TaskEffectVerificationEvidence(
            receipt_ids=tool_metrics["receipt_ids"],
            changed_paths=changed_paths,
            test_state=test_state,
        )
        verification = asyncio.run(
            SealedTaskEffectVerifier.capture(task).verify(
                workspace,
                evidence,
            )
        )
        if verification.infrastructure_error is not None:
            return _trial_failure(
                context,
                verification.infrastructure_error,
            )
        usage = _agent_usage(worker_result)
        recall = _recall_observation(
            isolation_root / "evaluation-recall.json",
        )
        clean_turn = _clean_worker_turn(worker_result)
        backend_module = worker_result.get("backend_module")
        control_isolated = bool(
            not treatment
            and backend_module is None
            and worker_result.get(
                "memory_backend_build_calls",
            )
            == 0
        )
        treatment_installed = bool(
            treatment and backend_module == "codecairn.integrations.pico.backend" and memory_receipt["seeded"] is True
        )
        worker_calls = tuple(
            call
            for call in worker_result.get(
                "model_calls",
                (),
            )
            if isinstance(call, Mapping)
        )
        accounting_complete = bool(
            usage["complete"]
            and proxy_calls
            and len(proxy_calls) == len(worker_calls)
            and all(call.get("accounting_valid") is True for call in proxy_calls)
        )
        actual_models = {
            str(call.get("model")).removeprefix(f"{_PROVIDER_NAME}/") for call in worker_calls if call.get("model")
        }
        model_matches = bool(actual_models) and (actual_models == {_PROVIDER_MODEL})
        production_complete = bool(
            clean_turn
            and accounting_complete
            and model_matches
            and (treatment_installed if treatment else control_isolated)
            and not fixture_file_drift(
                task.fixture,
                workspace,
            )
            and not (
                set(observed_repository_paths(workspace))
                - set(task.fixture.file_map)
                - {FIXTURE_MARKER}
                - set(task.allowed_mutation_paths)
            )
        )
        passed = verification.result.state is VerificationState.PASSED
        status = (
            TrialStatus.PASSED if passed else TrialStatus.TASK_FAILED if clean_turn else TrialStatus.PROVIDER_FAILURE
        )
        metrics = _trial_metrics(
            task,
            treatment=treatment,
            parent_owned_setup=parent_owned_setup,
            production_complete=production_complete,
            usage=usage,
            tool_metrics=tool_metrics,
            recall=recall,
            elapsed_ms=elapsed_ms,
            provider_cost=(ledger_after.provider_charged_cny - ledger_before.provider_charged_cny),
        )
        artifact = workspace.joinpath(*PurePosixPath(task.artifact_path).parts)
        refs = (artifact.relative_to(output_root).as_posix(),) if artifact.is_file() else ()
        return TrialExecution(
            status=status,
            runtime_state=(TurnTerminalState.COMPLETED if clean_turn else TurnTerminalState.ERROR),
            delivery_state=(
                DeliveryOutcome.DELIVERED if worker_result.get("delivery_events") else DeliveryOutcome.NO_OUTLET
            ),
            verification=verification.result,
            observed_variant_settings=dict(
                context.variant.settings,
            ),
            metrics=metrics,
            findings=(() if passed else tuple(verification.result.findings)),
            artifact_refs=refs,
        )

    def _prepare_workspace(
        self,
        task: TaskEffectTask,
        workspace: Path,
    ) -> bool:
        if task.parent_owned_mutation is None:
            build_repository_fixture(task, workspace)
            return True
        prior = build_parent_owned_prior_fixture(
            task,
            workspace,
        )
        contract = task.mutation_contract
        if contract is None or prior.fixture_digest != contract["prior_fixture_digest"]:
            raise ValueError(
                "parent-owned prior fixture digest changed",
            )
        mutation = task.parent_owned_mutation
        evaluated_file = task.fixture.file_map[mutation.path]
        target = workspace.joinpath(*PurePosixPath(mutation.path).parts)
        target.write_text(
            evaluated_file.content,
            encoding="utf-8",
        )
        if evaluated_file.executable:
            target.chmod(target.stat().st_mode | 0o111)
        marker = {
            "schema": FIXTURE_MARKER_SCHEMA,
            "fixture_id": task.fixture.fixture_id,
            "repository_id": task.fixture.repository_id,
            "revision": task.fixture.revision,
            "fixture_digest": task.fixture.digest,
        }
        (workspace / FIXTURE_MARKER).write_text(
            json.dumps(
                marker,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        if fixture_file_drift(task.fixture, workspace):
            raise ValueError(
                "parent-owned mutation did not produce evaluated fixture",
            )
        return True

    def _initialize_codecairn(
        self,
        repository: Path,
        runtime_root: Path,
        repo_key: str,
        environment: dict[str, str],
    ) -> dict[str, Any]:
        value = _command_json(
            (
                str(self._codecairn),
                "init",
                "--root",
                str(runtime_root),
                "--repo-key",
                repo_key,
                "--retrieval-profile",
                "fastembed",
                "--prefetch",
            ),
            cwd=repository,
            env=environment,
        )
        if not isinstance(value, Mapping):
            raise PairIntegrityError(
                "codecairn init returned invalid JSON",
            )
        return dict(value)

    def _seed_task_memory(
        self,
        task: TaskEffectTask,
        repository: Path,
        runtime_root: Path,
        environment: dict[str, str],
    ) -> dict[str, Any]:
        repo_key = task.fixture.repository_id
        if task.task_class is TaskClass.IRRELEVANT:
            content = task.prior_work_prompt
        else:
            source_definition = (
                task.parent_owned_mutation.prior_fixture(
                    task.fixture,
                )
                if task.parent_owned_mutation is not None
                else task.fixture
            )
            content = "\n\n".join(
                (
                    task.prior_work_prompt,
                    *(
                        f"Repository record {path}:\n{source_definition.file_map[path].content}"
                        for path in task.source_paths
                    ),
                )
            )
        subject_key = f"{task.task_id}_state"
        predecessor = self._remember(
            repository,
            runtime_root,
            repo_key=repo_key,
            subject_key=subject_key,
            title=task.title,
            content=content,
            environment=environment,
        )
        active = [predecessor]
        superseded: list[str] = []
        if task.parent_owned_mutation is not None:
            current_content = "\n\n".join(
                f"Current repository record {path}:\n{task.fixture.file_map[path].content}"
                for path in task.source_paths
            )
            successor = self._remember(
                repository,
                runtime_root,
                repo_key=repo_key,
                subject_key=subject_key,
                title=f"Current {task.title}",
                content=current_content,
                environment=environment,
            )
            self._supersede(
                repository,
                runtime_root,
                repo_key=repo_key,
                predecessor=predecessor,
                successor=successor,
                environment=environment,
            )
            active = [successor]
            superseded = [predecessor]
        return {
            "active_memory_ids": active,
            "expected_repo_key": repo_key,
            "seeded": True,
            "superseded_memory_ids": superseded,
        }

    def _remember(
        self,
        repository: Path,
        runtime_root: Path,
        *,
        repo_key: str,
        subject_key: str,
        title: str,
        content: str,
        environment: dict[str, str],
    ) -> str:
        value = _command_json(
            (
                str(self._codecairn),
                "remember",
                "repository_knowledge",
                content,
                "--title",
                title,
                "--subject-key",
                subject_key,
                "--repo-key",
                repo_key,
                "--root",
                str(runtime_root),
            ),
            cwd=repository,
            env=environment,
        )
        if not isinstance(value, Mapping) or not isinstance(
            value.get("memory_id"),
            str,
        ):
            raise PairIntegrityError(
                "codecairn remember returned invalid JSON",
            )
        return str(value["memory_id"])

    def _supersede(
        self,
        repository: Path,
        runtime_root: Path,
        *,
        repo_key: str,
        predecessor: str,
        successor: str,
        environment: dict[str, str],
    ) -> None:
        value = _command_json(
            (
                str(self._codecairn),
                "memory",
                "supersede",
                predecessor,
                successor,
                "--reason",
                "parent-owned repository revision replaced prior fact",
                "--repo-key",
                repo_key,
                "--root",
                str(runtime_root),
            ),
            cwd=repository,
            env=environment,
        )
        if not isinstance(value, Mapping):
            raise PairIntegrityError(
                "codecairn supersede returned invalid JSON",
            )

    def _write_trial_config(
        self,
        root: Path,
        proxy: _MeteredSemanticProxy,
    ) -> Path:
        provider = getattr(
            self._config.providers,
            _PROVIDER_NAME,
        ).model_dump(mode="json")
        provider["api_key"] = proxy.local_api_key
        provider["api_base"] = proxy.endpoint
        path = root / "runtime-config.json"
        path.write_text(
            json.dumps(
                {
                    "config": {
                        "agents": {
                            "defaults": {
                                "model": (self._config.agents.defaults.model),
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

    def _run_retrieval_sync(
        self,
        context: RetrievalContext,
    ) -> RetrievalExecution:
        located = self._retrieval.get(
            context.query.query_id,
        )
        if (
            located is None
            or context.key.query_id != context.query.query_id
            or context.configuration.configuration_id != "codecairn"
        ):
            return _retrieval_failure(
                "task_effect_retrieval_definition_mismatch",
            )
        definition, query = located
        expected = tuple(definition.anonymous_memory_id(memory_id) for memory_id in query.expected_memory_ids)
        if expected != context.query.expected_item_ids:
            return _retrieval_failure(
                "task_effect_retrieval_labels_changed",
            )
        try:
            with self._retrieval_lock:
                store = self._retrieval_stores.get(
                    definition.definition_kind,
                )
                if store is None:
                    store = self._build_retrieval_store(
                        definition,
                    )
                    self._retrieval_stores[definition.definition_kind] = store
                return store.recall(query)
        except (
            OSError,
            PairIntegrityError,
            TypeError,
            ValueError,
        ) as error:
            return _retrieval_failure(
                "task_effect_retrieval_failed:" + type(error).__name__,
            )

    def _build_retrieval_store(
        self,
        definition: RetrievalDefinition,
    ) -> _RetrievalStore:
        root = self._root / "retrieval" / definition.definition_kind.value
        runtime_root = root / "codecairn-runtime"
        environment = _minimal_environment(
            root / "home",
            {
                "CODECAIRN_MODEL_CACHE": str(
                    self._model_cache,
                ),
            },
        )
        repositories: dict[str, Path] = {}
        actual_to_memory: dict[
            str,
            RetrievalMemory,
        ] = {}
        hidden_memory_ids: set[str] = set()
        for repo_key in sorted({memory.repository_id for memory in definition.corpus}):
            repository = root / "repositories" / hashlib.sha256(repo_key.encode("utf-8")).hexdigest()[:16]
            _init_git_repository(repository)
            self._initialize_codecairn(
                repository,
                runtime_root,
                repo_key,
                environment,
            )
            repositories[repo_key] = repository
        for memory in definition.corpus:
            actual = self._remember(
                repositories[memory.repository_id],
                runtime_root,
                repo_key=memory.repository_id,
                subject_key=memory.memory_id.replace(
                    "-",
                    "_",
                ),
                title=memory.memory_id,
                content=memory.content,
                environment=environment,
            )
            actual_to_memory[actual] = memory
            if memory.validity is MemoryValidity.ACTIVE:
                continue
            successor = self._remember(
                repositories[memory.repository_id],
                runtime_root,
                repo_key=memory.repository_id,
                subject_key=memory.memory_id.replace(
                    "-",
                    "_",
                ),
                title=f"Retired {memory.memory_id}",
                content=(f"The prior record from {memory.source_uri} is retired and must not be used."),
                environment=environment,
            )
            hidden_memory_ids.add(successor)
            self._supersede(
                repositories[memory.repository_id],
                runtime_root,
                repo_key=memory.repository_id,
                predecessor=actual,
                successor=successor,
                environment=environment,
            )
        return _RetrievalStore(
            codecairn=self._codecairn,
            definition=definition,
            runtime_root=runtime_root,
            environment=environment,
            repositories=repositories,
            actual_to_memory=actual_to_memory,
            hidden_memory_ids=hidden_memory_ids,
        )

    def _validate_inputs(self) -> dict[str, Any]:
        for path in (
            self._pico_wheel,
            self._codecairn_wheel,
            self._stage_c_summary,
        ):
            if not path.is_file():
                raise ValueError(
                    f"task-effect campaign input is missing: {path.name}",
                )
        summary = _read_json(self._stage_c_summary)
        pico = summary.get("pico")
        codecairn = summary.get("codecairn")
        if (
            summary.get("schema") != _STAGE_C_SCHEMA
            or summary.get("passed") is not True
            or summary.get("paid_external_calls") != 0
            or not isinstance(pico, Mapping)
            or not isinstance(codecairn, Mapping)
            or pico.get("wheel_sha256") != _sha256(self._pico_wheel)
            or codecairn.get("wheel_sha256") != _sha256(self._codecairn_wheel)
        ):
            raise ValueError(
                "task-effect campaign inputs do not match Stage C",
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
        if source_status or pico.get("commit") != source_commit:
            raise ValueError(
                "PicoBench source must be the clean Stage C commit",
            )
        return dict(summary)


class _RetrievalStore:
    def __init__(
        self,
        *,
        codecairn: Path,
        definition: RetrievalDefinition,
        runtime_root: Path,
        environment: dict[str, str],
        repositories: Mapping[str, Path],
        actual_to_memory: Mapping[
            str,
            RetrievalMemory,
        ],
        hidden_memory_ids: set[str],
    ) -> None:
        self.codecairn = codecairn
        self.definition = definition
        self.runtime_root = runtime_root
        self.environment = environment
        self.repositories = dict(repositories)
        self.actual_to_memory = dict(actual_to_memory)
        self.hidden_memory_ids = set(hidden_memory_ids)

    def recall(
        self,
        query: RetrievalQuery,
    ) -> RetrievalExecution:
        started = time.perf_counter()
        value = _command_json(
            (
                str(self.codecairn),
                "recall",
                query.query_text,
                "--repo-key",
                query.repository_id,
                "--root",
                str(self.runtime_root),
                "--limit",
                "5",
                "--format",
                "json",
            ),
            cwd=self.repositories[query.repository_id],
            env=self.environment,
        )
        elapsed_ms = (time.perf_counter() - started) * 1_000
        if not isinstance(value, Mapping):
            raise PairIntegrityError(
                "codecairn recall returned invalid JSON",
            )
        sidecar = value.get("sidecar")
        if not isinstance(sidecar, Mapping):
            raise PairIntegrityError(
                "codecairn recall sidecar is missing",
            )
        ranked = sidecar.get("ranked")
        trace = sidecar.get("context_trace")
        admission = sidecar.get("admission_trace")
        if not isinstance(ranked, list) or not isinstance(trace, Mapping) or not isinstance(admission, Mapping):
            raise PairIntegrityError(
                "codecairn recall evidence is incomplete",
            )
        ranked_results: list[dict[str, Any]] = []
        result_by_actual: dict[
            str,
            dict[str, Any],
        ] = {}
        for raw in ranked:
            if not isinstance(raw, Mapping) or not isinstance(
                raw.get("memory_id"),
                str,
            ):
                raise PairIntegrityError(
                    "codecairn ranked result is invalid",
                )
            actual = str(raw["memory_id"])
            memory = self.actual_to_memory.get(
                actual,
            )
            if memory is None:
                if actual in self.hidden_memory_ids:
                    continue
                raise PairIntegrityError(
                    "codecairn returned an unknown memory identity",
                )
            result = {
                "item_id": (
                    self.definition.anonymous_memory_id(
                        memory.memory_id,
                    )
                ),
                "rank": len(ranked_results) + 1,
                "score": float(raw.get("final_score", 0.0)),
                "source": ("installed_codecairn_fastembed"),
                "repository_identity": (memory.repository_id),
                "validity_state": memory.validity.value,
                "anonymous": True,
            }
            ranked_results.append(result)
            result_by_actual[actual] = result
        rendered = trace.get(
            "rendered_memory_ids",
            (),
        )
        if not isinstance(rendered, list | tuple):
            raise PairIntegrityError(
                "codecairn rendered memory ids are invalid",
            )
        injected_results_list: list[dict[str, Any]] = []
        for actual in rendered:
            result = result_by_actual.get(str(actual))
            if result is not None:
                injected_results_list.append(
                    {
                        **result,
                        "injection_position": (len(injected_results_list) + 1),
                    }
                )
        injected_results = tuple(injected_results_list)
        abstained = not injected_results
        reason = (
            _abstention_reason(
                query.query_class,
            )
            if abstained
            else "not_abstained"
        )
        complete = bool(
            sidecar.get("repo_key") == query.repository_id
            and sidecar.get("retrieval_profile")
            and sidecar.get("semantic_state") == "complete"
            and admission.get("outcome") in {"admitted", "abstained"}
        )
        return RetrievalExecution(
            status=RetrievalStatus.MEASURABLE,
            ranked_results=tuple(ranked_results),
            injected_results=injected_results,
            usage={
                "usage.complete": True,
                "cost.complete": True,
                "embedding_calls": 1,
                "semantic_calls": 0,
                "reranking_calls": int(bool(ranked_results)),
                "cost_cny": 0.0,
            },
            metadata={
                "query_class": query.query_class.value,
                "repository_id": query.repository_id,
                "abstained": abstained,
                "abstention_reason": reason,
                "retrieval_latency_ms": elapsed_ms,
                "production_evidence_complete": complete,
                "memory_off_operation_calls": 0,
                "anonymous_candidate_ids": [result["item_id"] for result in ranked_results],
                "anonymous_injected_ids": [result["item_id"] for result in injected_results],
            },
        )


def _task_prompt(
    task: TaskEffectTask,
) -> str:
    return (
        f"{task.evaluation_prompt}\n\n"
        "You are operating in the repository root. "
        "Use read_file for the required repository evidence, "
        "write_file for the requested JSON artifact, and exec "
        f"with exactly `{task.test_command}` after writing it. "
        "Do not modify any other path. Complete the task without "
        "asking questions."
    )


def _file_digests(
    root: Path,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _is_runtime_owned(relative):
            continue
        if path.is_file() and not path.is_symlink():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _remove_runtime_paths(
    workspace: Path,
) -> None:
    for relative in _RUNTIME_OWNED_PATHS:
        target = workspace.joinpath(*relative.parts)
        if target.is_symlink():
            raise ValueError(
                "runtime-owned path cannot be a symlink",
            )
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            raise ValueError(
                "runtime-owned path has unexpected type",
            )


def _is_runtime_owned(
    relative: Path,
) -> bool:
    candidate = PurePosixPath(relative.as_posix())
    return any(candidate == owned or candidate.is_relative_to(owned) for owned in _RUNTIME_OWNED_PATHS)


def _tool_receipts(
    raw_events: object,
) -> dict[str, Any]:
    events = raw_events if isinstance(raw_events, list | tuple) else ()
    receipts: list[str] = []
    reads: list[str] = []
    tool_calls = 0
    failures = 0
    search_calls = 0
    test_calls = 0
    write_calls = 0
    for event in events:
        if not isinstance(event, Mapping) or event.get("phase") != "complete":
            continue
        tool_calls += 1
        if event.get("failed") is True:
            failures += 1
            continue
        name = event.get("name")
        arguments = event.get("arguments")
        if not isinstance(arguments, Mapping):
            continue
        if name == "read_file":
            path = arguments.get("path")
            if isinstance(path, str):
                receipts.append(f"read:{path}")
                reads.append(path)
        elif name == "write_file":
            path = arguments.get("path")
            if isinstance(path, str):
                receipts.append(f"write:{path}")
                write_calls += 1
        elif name == "exec":
            command = arguments.get("command")
            if isinstance(command, str):
                receipts.append(f"test:{command}")
                test_calls += 1
        elif name in {"find", "grep", "list_dir"}:
            search_calls += 1
    repeated = sum(count - 1 for count in Counter(reads).values() if count > 1)
    return {
        "receipt_ids": tuple(dict.fromkeys(receipts)),
        "repository_read_calls": len(reads),
        "repository_search_calls": search_calls,
        "test_calls": test_calls,
        "write_calls": write_calls,
        "tool_calls": tool_calls,
        "tool_failures": failures,
        "repeated_repository_reads": repeated,
    }


def _agent_usage(
    result: Mapping[str, Any],
) -> dict[str, int | bool]:
    calls = tuple(call for call in result.get("model_calls", ()) if isinstance(call, Mapping))
    usages = tuple(call.get("usage") for call in calls if isinstance(call.get("usage"), Mapping))
    complete = bool(
        calls
        and len(calls) == len(usages)
        and all(
            isinstance(usage.get("prompt_tokens"), int)
            and isinstance(
                usage.get("completion_tokens"),
                int,
            )
            and isinstance(
                usage.get("total_tokens"),
                int,
            )
            and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
            for usage in usages
        )
    )
    input_tokens = sum(
        int(usage["prompt_tokens"])
        for usage in usages
        if isinstance(
            usage.get("prompt_tokens"),
            int,
        )
    )
    output_tokens = sum(
        int(usage["completion_tokens"])
        for usage in usages
        if isinstance(
            usage.get("completion_tokens"),
            int,
        )
    )
    return {
        "complete": complete,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (input_tokens + output_tokens),
    }


def _recall_observation(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "hit_count": 0,
            "injected_count": 0,
            "latency_ms": 0.0,
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "hit_count": 0,
            "injected_count": 0,
            "latency_ms": 0.0,
        }
    hits = value.get("hits", ())
    return {
        "hit_count": (len(hits) if isinstance(hits, list | tuple) else 0),
        "injected_count": (len(hits) if isinstance(hits, list | tuple) else 0),
        "latency_ms": float(value.get("latency_ms", 0.0)),
    }


def _trial_metrics(
    task: TaskEffectTask,
    *,
    treatment: bool,
    parent_owned_setup: bool,
    production_complete: bool,
    usage: Mapping[str, int | bool],
    tool_metrics: Mapping[str, Any],
    recall: Mapping[str, Any],
    elapsed_ms: float,
    provider_cost: float,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "task_effect.production_evidence_complete": (production_complete),
        "task_effect.fixture_digest": task.fixture.digest,
        "task_effect.expected_digest": task.expected_digest,
        "task_effect.verifier_id": ("external_parent_owned_task_effect_v2"),
        "task_effect.parent_owned_setup_complete": (parent_owned_setup),
        "task_effect.fixture_reset_complete": True,
        "usage.complete": usage["complete"],
        "cost.complete": True,
        "usage.main_agent_input_tokens": usage["input_tokens"],
        "usage.main_agent_output_tokens": usage["output_tokens"],
        "usage.trial_total_tokens": usage["total_tokens"],
        "runtime.repository_read_calls": tool_metrics["repository_read_calls"],
        "runtime.repository_search_calls": tool_metrics["repository_search_calls"],
        "runtime.test_calls": tool_metrics["test_calls"],
        "runtime.write_calls": tool_metrics["write_calls"],
        "runtime.tool_calls": tool_metrics["tool_calls"],
        "runtime.repeated_repository_reads": tool_metrics["repeated_repository_reads"],
        "runtime.end_to_end_latency_ms": elapsed_ms,
        "runtime.retrieval_latency_ms": recall["latency_ms"],
        "cost.provider_cny": provider_cost,
        "cost.codecairn_cny": 0.0,
        "cost.total_cny": provider_cost,
        "codecairn.memory_off_operation_calls": (0 if not treatment else None),
        "codecairn.memory_hits": (recall["hit_count"] if treatment else 0),
        "codecairn.injected_items": (recall["injected_count"] if treatment else 0),
        "codecairn.abstentions": int(treatment and recall["injected_count"] == 0),
        "codecairn.memory_failures": 0,
    }
    if task.mutation_contract is not None:
        metrics.update(
            {
                "task_effect.parent_owned_prior_fixture_digest": (task.mutation_contract["prior_fixture_digest"]),
                "task_effect.evaluated_fixture_digest": (task.mutation_contract["evaluated_fixture_digest"]),
                "task_effect.parent_owned_mutation_contract_digest": (task.mutation_contract["contract_digest"]),
            }
        )
    return metrics


def _clean_worker_turn(
    result: Mapping[str, Any],
) -> bool:
    outcome = result.get("outcome")
    return bool(
        result.get("terminal") == "completed"
        and result.get("close_error") is None
        and isinstance(outcome, Mapping)
        and outcome.get("status") == "completed"
    )


def _abstention_reason(
    query_class: RetrievalQueryClass,
) -> str:
    return {
        RetrievalQueryClass.FACT_POSITIVE: ("no_relevant_memory"),
        RetrievalQueryClass.EXPERIENCE_POSITIVE: ("no_relevant_memory"),
        RetrievalQueryClass.HARD_NEGATIVE: ("no_relevant_memory"),
        RetrievalQueryClass.STALE: ("stale_or_superseded_filtered"),
        RetrievalQueryClass.CROSS_REPOSITORY: ("cross_repository_memory_filtered"),
    }[query_class]


def _trial_id(
    context: TrialContext,
) -> str:
    return (
        f"{context.experiment_id}/{context.key.pack_id}/"
        f"{context.key.task_id}/"
        f"{context.key.variant_id}/"
        f"{context.key.repetition}/"
        f"{context.block_attempt}/agent"
    )


def _trial_failure(
    context: TrialContext,
    finding: str,
) -> TrialExecution:
    return TrialExecution(
        status=TrialStatus.INFRASTRUCTURE_FAILURE,
        runtime_state=TurnTerminalState.ERROR,
        delivery_state=DeliveryOutcome.NO_OUTLET,
        verification=VerifierResult(
            state=VerificationState.NOT_RUN,
        ),
        observed_variant_settings=dict(
            context.variant.settings,
        ),
        findings=(finding,),
    )


def _retrieval_failure(
    finding: str,
) -> RetrievalExecution:
    return RetrievalExecution(
        status=RetrievalStatus.INFRASTRUCTURE_FAILURE,
        findings=(finding,),
    )


__all__ = ["ProductionTaskEffectRunner"]
