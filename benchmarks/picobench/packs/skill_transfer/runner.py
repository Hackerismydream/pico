from __future__ import annotations

import asyncio
import hashlib
import http.server
import json
import os
import shutil
import ssl
import subprocess
import textwrap
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

import certifi

from benchmarks.picobench.budget import (
    BudgetGuardedProvider,
    ProviderBudgetConfig,
    ProviderBudgetLedger,
    provider_call_budget_scope,
)
from benchmarks.picobench.canonical import canonical_digest
from pico.providers.base import LLMProvider
from pico.providers.litellm_provider import LiteLLMProvider

from ..myna_task_effect.runner import InstalledTrialExecutor, _tool_metrics
from .campaign import (
    AbilityDefinition,
    CampaignConfig,
    HeldOutInstance,
    NegativeRecord,
    SkillTransferCorpus,
    TrialRecord,
    directory_digest,
    learning_projection,
)
from .fixtures import materialize, verify


class InstalledSkillTransferExecutor(InstalledTrialExecutor):
    def __init__(
        self,
        config: CampaignConfig,
        *,
        provider_api_key: str,
        provider_api_base: str | None,
        skill_provider_override: LLMProvider | None = None,
    ) -> None:
        if not provider_api_key:
            raise ValueError("skill transfer Provider credential is required")
        super().__init__(config)  # type: ignore[arg-type]
        shared_model_cache = os.environ.get("PICO_BENCH_MODEL_CACHE")
        if shared_model_cache:
            self._model_cache = Path(shared_model_cache).resolve()
            self._model_cache.mkdir(parents=True, exist_ok=True)
        self._config = config
        self._provider_api_key = provider_api_key
        self._provider_api_base = provider_api_base
        self._skill_provider_override = skill_provider_override
        self._candidate_worker = Path(__file__).with_name("candidate_worker.py").resolve()
        self._benchmark_root = Path(__file__).resolve().parents[4]
        self._budget_path: Path | None = None
        self._budget_config: ProviderBudgetConfig | None = None
        self._snapshots: dict[str, dict[str, Any]] = {}

    def configure_budget(self, path: Path, config: ProviderBudgetConfig) -> None:
        self._budget_path = path.resolve()
        self._budget_config = config

    def prepare_candidates(self, corpus: SkillTransferCorpus, *, snapshot_root: Path) -> dict[str, Any]:
        if self._budget_path is None or self._budget_config is None:
            raise ValueError("skill transfer budget is not configured")
        provider = self._skill_provider_override or _skill_provider(
            api_key=self._provider_api_key,
            api_base=self._provider_api_base,
            ledger=ProviderBudgetLedger(self._budget_path, self._budget_config),
        )
        if not isinstance(provider, BudgetGuardedProvider):
            raise ValueError("Skill extraction Provider must be budget guarded")
        active: dict[str, str] = {}
        experiences: dict[str, list[str]] = {}
        facts: dict[str, list[str]] = {}
        learning: dict[str, list[str]] = {}
        learning_experience_maps: dict[str, dict[str, str]] = {}
        skills: dict[str, dict[str, Any]] = {}
        snapshot_digests: dict[str, dict[str, str]] = {}
        with _skill_proxy(self._root / "skill-proxy", provider, config=self._config) as proxy:
            for ability in corpus.abilities:
                result = self._candidate_call_with_local_recovery(
                    ability_id=ability.ability_id,
                    ability=learning_projection(ability),
                    environment_overrides={
                        "MYNA_SEMANTIC_API_KEY": "budgeted-local-proxy",
                        "MYNA_SEMANTIC_ENDPOINT": proxy.endpoint,
                        "MYNA_SEMANTIC_MODEL": "deepseek-v4-flash",
                        "SSL_CERT_FILE": str(proxy.certificate),
                    },
                )
                if result.get("ability_id") != ability.ability_id:
                    raise RuntimeError("candidate worker returned the wrong ability")
                persisted = snapshot_root / ability.ability_id
                persisted.mkdir(parents=True)
                for arm_id in ("control", "treatment"):
                    destination = persisted / f"{arm_id}-runtime"
                    shutil.copytree(Path(result[f"{arm_id}_runtime"]), destination)
                    result[f"{arm_id}_runtime"] = str(destination)
                snapshot_digests[ability.ability_id] = {
                    arm_id: directory_digest(persisted / f"{arm_id}-runtime") for arm_id in ("control", "treatment")
                }
                self._snapshots[ability.ability_id] = result
                active[ability.ability_id] = str(result["active_revision_id"])
                experiences[ability.ability_id] = [str(item) for item in result["source_experience_ids"]]
                facts[ability.ability_id] = [str(item) for item in result["source_fact_ids"]]
                learning[ability.ability_id] = [item.instance_id for item in ability.learning]
                learning_experience_maps[ability.ability_id] = {
                    str(key): str(value) for key, value in result["learning_experience_map"].items()
                }
                skill = result.get("skill")
                if not isinstance(skill, dict):
                    raise RuntimeError("candidate worker did not return reviewable Skill content")
                skills[ability.ability_id] = skill
        receipt = {
            "schema": "pico.picobench.skill-transfer.candidate-receipt.v1",
            "candidate_input_digest": canonical_digest([learning_projection(ability) for ability in corpus.abilities]),
            "active_revisions": active,
            "source_experience_ids": experiences,
            "source_fact_ids": facts,
            "source_learning_instance_ids": learning,
            "learning_experience_maps": learning_experience_maps,
            "skills": skills,
            "runtime_snapshot_digests": snapshot_digests,
            "extractor": {
                "provider": self._config.provider,
                "model": self._config.model,
                "prompt_revision": "myna-skill-extractor-v1",
                "thinking": "disabled",
                "provider_request_attempts": provider.ledger.snapshot().request_attempts,
            },
        }
        receipt["held_out_admission_precheck"] = self.admission_precheck(corpus)
        receipt["candidate_frozen_before_admission_precheck"] = True
        return receipt

    def load_candidates(self, corpus: SkillTransferCorpus, receipt: dict[str, Any], *, snapshot_root: Path) -> None:
        active = receipt.get("active_revisions", {})
        experiences = receipt.get("source_experience_ids", {})
        digests = receipt.get("runtime_snapshot_digests", {})
        for ability in corpus.abilities:
            snapshot = snapshot_root / ability.ability_id
            control = snapshot / "control-runtime"
            treatment = snapshot / "treatment-runtime"
            if not control.is_dir() or not treatment.is_dir():
                raise ValueError("persisted candidate runtime snapshot is incomplete")
            observed = {
                "control": directory_digest(control),
                "treatment": directory_digest(treatment),
            }
            if digests.get(ability.ability_id) != observed:
                raise ValueError("persisted candidate runtime snapshot digest does not match")
            self._snapshots[ability.ability_id] = {
                "ability_id": ability.ability_id,
                "active_revision_id": active[ability.ability_id],
                "control_runtime": str(control),
                "source_experience_ids": experiences[ability.ability_id],
                "treatment_runtime": str(treatment),
            }

    def run_trial(
        self,
        ability: AbilityDefinition,
        task: HeldOutInstance,
        repetition: int,
        arm_id: str,
    ) -> TrialRecord:
        if self._budget_path is None or self._budget_config is None or ability.ability_id not in self._snapshots:
            raise ValueError("skill transfer candidate preparation is incomplete")
        snapshot = self._snapshots[ability.ability_id]
        trial_root = self._root / "trials" / task.instance_id / str(repetition) / arm_id
        workspace = trial_root / "repository"
        workspace.mkdir(parents=True)
        paths = materialize(workspace, task.fixture)
        self._run(("git", "init", "-q"), cwd=workspace)
        fixture_digest = canonical_digest(
            {path: hashlib.sha256((workspace / path).read_bytes()).hexdigest() for path in sorted(paths)}
        )
        smoke_digest = hashlib.sha256((workspace / "smoke.py").read_bytes()).hexdigest()
        runtime = trial_root / "myna-runtime"
        source_runtime = Path(snapshot[f"{arm_id}_runtime"])
        shutil.copytree(source_runtime, runtime)
        self._run(
            (
                str(self._myna),
                "init",
                "--root",
                str(runtime),
                "--repo-key",
                f"skill-transfer/{ability.ability_id}",
            ),
            cwd=workspace,
            environment_overrides={"MYNA_SEMANTIC_API_KEY": ""},
        )
        started = time.monotonic_ns()
        worker = self._worker_call(
            self._turn_spec(
                ability, task, repetition=repetition, arm_id=arm_id, workspace=workspace, state=trial_root / "state"
            ),
            trial_root / "worker",
            environment_overrides={
                "MYNA_SEMANTIC_API_KEY": "",
                "PICO_BENCH_PROVIDER_API_KEY": self._provider_api_key,
            },
        )
        latency_ms = max(0, round((time.monotonic_ns() - started) / 1_000_000))
        receipt = verify(workspace, task.fixture)
        smoke_unchanged = hashlib.sha256((workspace / "smoke.py").read_bytes()).hexdigest() == smoke_digest
        observed_paths = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file()
            and not path.is_relative_to(workspace / ".git")
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        }
        unexpected_paths = sorted(observed_paths - set(paths))
        receipt["smoke_fixture_unchanged"] = smoke_unchanged
        receipt["unexpected_workspace_paths"] = unexpected_paths
        passed = bool(
            receipt["passed"] and smoke_unchanged and not unexpected_paths and worker.get("terminal") == "completed"
        )
        failure_class = worker.get("failure_class")
        if failure_class is None and not passed:
            failure_class = "task"
        qualified = tuple(str(item) for item in worker.get("injected_skill_ids", ()))
        revision = str(snapshot["active_revision_id"])
        injected = tuple(revision for item in qualified if item.endswith(f"@{revision}"))
        metrics = _tool_metrics(worker.get("tool_events"))
        input_tokens = int(worker.get("input_tokens", 0) or 0)
        output_tokens = int(worker.get("output_tokens", 0) or 0)
        return TrialRecord(
            task_id=task.instance_id,
            ability_id=ability.ability_id,
            repetition=repetition,
            arm_id=arm_id,  # type: ignore[arg-type]
            status="passed" if passed else "task_failed" if failure_class == "task" else "infrastructure_failure",
            workspace_digest=fixture_digest,
            active_revision_id=revision if arm_id == "treatment" else None,
            injected_skill_ids=injected,
            source_experience_ids=tuple(str(item) for item in snapshot["source_experience_ids"]),
            tool_calls=metrics["tool_calls"],
            turns=1,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_calls=int(worker.get("provider_calls", 0) or 0),
            estimated_cost_cny=self._budget_config.cost_cny(input_tokens, output_tokens),
            verification_receipt=receipt,
            failure_class=None if passed else str(failure_class),
        )

    def hard_negatives(self, corpus: SkillTransferCorpus) -> tuple[NegativeRecord, ...]:
        records: list[NegativeRecord] = []
        for ability in corpus.abilities:
            snapshot = self._snapshots[ability.ability_id]
            results = self._recall_queries(
                ability,
                {item.instance_id: item.query for item in ability.hard_negatives},
                category="negatives",
            )
            for item in ability.hard_negatives:
                result = results[item.instance_id]
                records.append(
                    NegativeRecord(
                        instance_id=item.instance_id,
                        ability_id=ability.ability_id,
                        active_revision_id=str(snapshot["active_revision_id"]),
                        recalled_revision_ids=tuple(str(value) for value in result["recalled_revision_ids"]),
                    )
                )
        return tuple(records)

    def admission_precheck(self, corpus: SkillTransferCorpus) -> dict[str, list[str]]:
        results: dict[str, list[str]] = {}
        for ability in corpus.abilities:
            observed = self._recall_queries(
                ability,
                {item.instance_id: item.prompt for item in ability.held_out},
                category="admission",
            )
            for item in ability.held_out:
                results[item.instance_id] = [
                    str(value) for value in observed[item.instance_id]["recalled_revision_ids"]
                ]
        return results

    def _recall_queries(
        self,
        ability: AbilityDefinition,
        queries: dict[str, str],
        *,
        category: str,
    ) -> dict[str, Any]:
        snapshot = self._snapshots[ability.ability_id]
        root = self._root / category / ability.ability_id
        workspace = root / "repository"
        workspace.mkdir(parents=True)
        self._run(("git", "init", "-q"), cwd=workspace)
        runtime = root / "myna-runtime"
        shutil.copytree(Path(snapshot["treatment_runtime"]), runtime)
        self._run(
            (
                str(self._myna),
                "init",
                "--root",
                str(runtime),
                "--repo-key",
                f"skill-transfer/{ability.ability_id}",
            ),
            cwd=workspace,
            environment_overrides={"MYNA_SEMANTIC_API_KEY": ""},
        )
        result = self._candidate_call(
            {"mode": "recall_many", "repository": str(workspace), "queries": queries},
            root / "worker",
            environment_overrides={"MYNA_SEMANTIC_API_KEY": ""},
        )
        if set(result) != set(queries):
            raise RuntimeError("Skill admission precheck returned an incomplete query set")
        return result

    def _turn_spec(
        self,
        ability: AbilityDefinition,
        task: HeldOutInstance,
        *,
        repetition: int,
        arm_id: str,
        workspace: Path,
        state: Path,
    ) -> dict[str, Any]:
        if self._budget_path is None or self._budget_config is None:
            raise ValueError("skill transfer budget is not configured")
        budget = asdict(self._budget_config)
        return {
            "worker_mode": "turn",
            "arm_id": arm_id,
            "agent_track_only": True,
            "memory_enabled": True,
            "skill_forge_enabled": True,
            "stage": "evaluate",
            "task_id": task.instance_id,
            "task_class": ability.ability_id,
            "source_path": "solution.py",
            "output_path": "solution.py",
            "workspace": str(workspace),
            "state_root": str(state),
            "prompt": (
                f"{task.prompt}\n\nWork only in solution.py. The public smoke check is smoke.py. "
                "Implement the requested behavior and run useful checks before finishing."
            ),
            "session_id": f"{task.instance_id}-{repetition}-{arm_id}",
            "message_id": f"{task.instance_id}-{repetition}-{arm_id}",
            "timeout_seconds": 180,
            "provider_mode": "live",
            "provider_name": self._config.provider,
            "provider_api_base": self._provider_api_base,
            "model": self._config.model,
            "benchmark_root": str(self._benchmark_root),
            "trial_id": f"{task.instance_id}:{repetition}:{arm_id}",
            "max_tool_iterations": self._config.max_tool_iterations,
            "max_logical_calls_per_trial": self._config.max_tool_iterations + 1,
            "max_attempts_per_call": self._config.max_attempts_per_call,
            "max_input_tokens_per_call": self._config.max_input_tokens_per_call,
            "max_output_tokens_per_call": self._config.max_output_tokens_per_call,
            "context_window_tokens": 16_384,
            "disabled_tools": ["ask_user", "message", "spawn", "understand_media", "web_fetch", "web_search"],
            "budget": {
                "ledger_path": str(self._budget_path),
                "hard_cap_cny": budget["hard_cap_cny"],
                "maximum_provider_attempts": budget["max_total_request_attempts"],
                "input_cache_miss_usd_per_million": budget["input_cache_miss_usd_per_million"],
                "output_usd_per_million": budget["output_usd_per_million"],
                "conservative_usd_to_cny_multiplier": budget["conservative_usd_to_cny_multiplier"],
                "approval_digest": budget["approval_digest"],
                "ledger_prefix_event_count": budget["ledger_prefix_event_count"],
                "ledger_prefix_digest": budget["ledger_prefix_digest"],
                "ledger_prefix_charged_cny": budget["ledger_prefix_charged_cny"],
            },
        }

    def _candidate_call(
        self,
        spec: dict[str, Any],
        root: Path,
        *,
        environment_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        root.mkdir(parents=True, exist_ok=True)
        spec_path = root / "spec.json"
        spec_path.write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
        completed = self._run(
            (str(self._python), "-I", str(self._candidate_worker), str(spec_path)),
            cwd=root,
            environment_overrides=environment_overrides,
        )
        value = json.loads(completed.stdout.splitlines()[-1])
        if not isinstance(value, dict):
            raise RuntimeError("candidate worker returned non-object JSON")
        return value

    def _candidate_call_with_local_recovery(
        self,
        *,
        ability_id: str,
        ability: dict[str, Any],
        environment_overrides: dict[str, str],
    ) -> dict[str, Any]:
        for local_attempt in range(3):
            ability_root = self._root / "candidates" / ability_id / f"local-{local_attempt + 1}"
            try:
                return self._candidate_call(
                    {"root": str(ability_root), "ability": ability},
                    ability_root / "worker",
                    environment_overrides=environment_overrides,
                )
            except RuntimeError as error:
                retryable = "exit -6" in str(error) and "recursive_mutex lock failed" in str(error)
                if not retryable or local_attempt == 2:
                    raise
        raise AssertionError("unreachable candidate recovery state")


def _skill_provider(*, api_key: str, api_base: str | None, ledger: ProviderBudgetLedger) -> BudgetGuardedProvider:
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model="deepseek/deepseek-v4-flash",
        provider_name="deepseek",
        extra_body={"thinking": {"type": "disabled"}},
    )
    return BudgetGuardedProvider(provider, ledger=ledger)


def _cacheable_skill_content(content: str) -> bool:
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return False
    fields = {"name", "description", "applicability", "procedure", "verification", "failure_avoidance"}
    return bool(
        isinstance(value, dict)
        and set(value) == fields
        and all(isinstance(value[field], str) and value[field].strip() for field in ("name", "description"))
        and all(
            isinstance(value[field], list)
            and (field == "failure_avoidance" or bool(value[field]))
            and all(isinstance(item, str) and item.strip() for item in value[field])
            for field in ("applicability", "procedure", "verification", "failure_avoidance")
        )
    )


class _Proxy:
    def __init__(self, endpoint: str, certificate: Path) -> None:
        self.endpoint = endpoint
        self.certificate = certificate


@contextmanager
def _skill_proxy(root: Path, provider: BudgetGuardedProvider, *, config: CampaignConfig) -> Iterator[_Proxy]:
    root.mkdir(parents=True)
    certificate, key = _certificate(root)
    trust_bundle = root / "ca-bundle.pem"
    trust_bundle.write_bytes(Path(certifi.where()).read_bytes() + b"\n" + certificate.read_bytes())
    response_cache: dict[str, str] = {}
    response_cache_lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            messages = request.get("messages", [])
            system = str(messages[0].get("content", "")) if messages else ""
            if "exactly these six fields" not in system:
                content = json.dumps({"candidates": [], "evolution": []}, sort_keys=True)
                usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            else:
                ability = json.loads(messages[-1]["content"])["ability_fingerprint"]
                cache_key = canonical_digest(request)
                with response_cache_lock:
                    content = response_cache.get(cache_key)
                if content is None:
                    with provider_call_budget_scope(
                        trial_id=f"skill-extraction:{ability}",
                        max_logical_calls=1,
                        max_attempts_per_call=config.max_attempts_per_call,
                        max_input_tokens_per_call=config.max_input_tokens_per_call,
                        max_output_tokens_per_call=config.max_output_tokens_per_call,
                    ):
                        response = asyncio.run(
                            provider.chat(
                                messages,
                                model=config.model,
                                max_tokens=config.max_output_tokens_per_call,
                                temperature=0,
                            )
                        )
                    if response.finish_reason == "error" or not response.content:
                        raise RuntimeError("Skill extraction Provider failed")
                    content = response.content
                    usage = response.usage
                    if _cacheable_skill_content(content):
                        with response_cache_lock:
                            response_cache[cache_key] = content
                else:
                    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            encoded = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": usage}, sort_keys=True
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Proxy(f"https://localhost:{server.server_port}/v1", trust_bundle)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _certificate(root: Path) -> tuple[Path, Path]:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError("openssl is required for the budgeted Skill extraction proxy")
    certificate, key, config = root / "cert.pem", root / "key.pem", root / "openssl.cnf"
    config.write_text(
        textwrap.dedent("""
            [req]
            distinguished_name = dn
            x509_extensions = ext
            prompt = no
            [dn]
            CN = localhost
            [ext]
            basicConstraints = critical, CA:TRUE
            subjectAltName = DNS:localhost
            keyUsage = digitalSignature, keyEncipherment, keyCertSign
            extendedKeyUsage = serverAuth
        """),
        encoding="utf-8",
    )
    subprocess.run(
        (
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-config",
            str(config),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    return certificate, key


__all__ = ["InstalledSkillTransferExecutor"]
