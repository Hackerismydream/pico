from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.server
import json
import os
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import textwrap
import threading
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from typing import Any, Iterator

EXPECTED_PLUGIN_ID = "myna-memory"
EXPECTED_PLUGIN_VERSION = "0.1.1rc3"
EXPECTED_COMPATIBILITY = ">=0.1,<0.2"
EXPECTED_BACKEND = "myna"
EXPECTED_FACTORY = "myna.integrations.pico:make_backend"
MEMORY_TEXT = "Pico releases require make check."
SKILL_QUERY = "Apply the repository verification workflow."
SKILL_PROCEDURE = "Run make check from the repository root."


class VerificationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


class _RecordingProvider:
    def __new__(cls):
        from pico.providers.base import LLMProvider, LLMResponse

        class Provider(LLMProvider):
            def __init__(self) -> None:
                super().__init__(api_key="installed-smoke")
                self.messages: list[dict[str, Any]] = []

            async def chat(
                self,
                messages,
                tools=None,
                model=None,
                max_tokens=4096,
                temperature=0.7,
                reasoning_effort=None,
                tool_choice=None,
            ):
                self.messages = messages
                return LLMResponse(content="acknowledged", finish_reason="stop")

            def get_default_model(self) -> str:
                return "installed-smoke"

        return Provider()


class _VerifyingProvider:
    def __new__(cls):
        from pico.providers.base import LLMProvider, LLMResponse, ToolCallRequest

        class Provider(LLMProvider):
            def __init__(self) -> None:
                super().__init__(api_key="installed-smoke")
                self._requested_check = False

            async def chat(
                self,
                messages,
                tools=None,
                model=None,
                max_tokens=4096,
                temperature=0.7,
                reasoning_effort=None,
                tool_choice=None,
            ):
                if not self._requested_check:
                    self._requested_check = True
                    return LLMResponse(
                        content="",
                        tool_calls=[ToolCallRequest(id="verify", name="exec", arguments={"command": "make check"})],
                        finish_reason="tool_calls",
                    )
                return LLMResponse(content="Repository verification completed.", finish_reason="stop")

            def get_default_model(self) -> str:
                return "installed-smoke"

        return Provider()


class _SemanticHandler(http.server.BaseHTTPRequestHandler):
    skill_requests = 0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        messages = request.get("messages", [])
        system = str(messages[0].get("content", "")) if messages else ""
        if "exactly these six fields" in system:
            type(self).skill_requests += 1
            content = {
                "name": "Repository verification",
                "description": "Apply the repository verification workflow safely.",
                "applicability": ["Use when applying the repository verification workflow."],
                "procedure": [SKILL_PROCEDURE],
                "verification": ["Require make check to exit with code zero."],
                "failure_avoidance": ["Do not claim success when the check fails."],
            }
        else:
            content = {"candidates": [], "evolution": []}
        encoded = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": json.dumps(content, sort_keys=True)}}]},
            sort_keys=True,
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify installed Pico and Myna wheel composition")
    parser.add_argument("--pico-wheel", type=Path, required=True)
    parser.add_argument("--myna-wheel", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--myna-source-root", type=Path, required=True)
    parser.add_argument("--myna-sha256", required=True)
    parser.add_argument("--phase", choices=("store", "recall"))
    parser.add_argument("--repository", type=Path)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repository: Path, *arguments: str) -> None:
    git = shutil.which("git")
    if git is None:
        raise VerificationError("git executable is unavailable")
    subprocess.run((git, "-C", str(repository), *arguments), check=True, capture_output=True, text=True)


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _semantic_server(root: Path) -> Iterator[tuple[str, Path]]:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise VerificationError("openssl executable is unavailable")
    certificate = root / "semantic-cert.pem"
    private_key = root / "semantic-key.pem"
    openssl_config = root / "openssl.cnf"
    openssl_config.write_text(
        textwrap.dedent("""
            [req]
            distinguished_name = distinguished_name
            x509_extensions = extensions
            prompt = no

            [distinguished_name]
            CN = localhost

            [extensions]
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
            str(private_key),
            "-out",
            str(certificate),
            "-config",
            str(openssl_config),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    _SemanticHandler.skill_requests = 0
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SemanticHandler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, private_key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, name="myna-semantic-smoke", daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_port}/v1", certificate
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _myna_cli(
    repository: Path, environment: dict[str, str], *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    executable = Path(sys.executable).parent / "myna"
    return subprocess.run(
        (str(executable), *arguments),
        cwd=repository,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


def _myna_cli_json(repository: Path, environment: dict[str, str], *arguments: str) -> dict[str, Any]:
    completed = _myna_cli(repository, environment, *arguments)
    return json.loads(completed.stdout)


def _registry():
    from pico.cli._plugin_stack import build_plugin_registry
    from pico.config.pico import PicoConfig

    return build_plugin_registry(PicoConfig())


def _backend(repository: Path):
    from pico.cli._plugin_stack import maybe_build_memory_backend
    from pico.config.pico import PicoConfig

    return maybe_build_memory_backend(repository, PicoConfig(), registry=_registry())


async def _runtime_turn(repository: Path, state: Path, *, memory_backend: str | None) -> None:
    from pico.cli._runtime_assembly import assemble_runtime
    from pico.config.paths import RuntimePaths
    from pico.config.pico import MemoryConfig, PicoConfig
    from pico.config.schema import Config
    from pico.spine.message import ChatType, Source
    from pico.spine.turn import Origin, TurnRequest

    state.mkdir(parents=True)
    config = Config()
    config.agents.defaults.workspace = str(repository)
    config.agents.defaults.model = "installed-smoke"
    config.agents.defaults.enable_personalization = False
    config.routing.enabled = False
    pico_config = PicoConfig(memory=MemoryConfig(backend=memory_backend))
    pico_config.base = config
    pico_config.skill_forge.enabled = False
    pico_config.skill_forge.router.enabled = False
    runtime = assemble_runtime(
        config,
        pico_config,
        provider=_RecordingProvider(),
        cron_service=None,
        interactive=False,
        paths=RuntimePaths(workspace=repository, state=state),
    )
    _require((runtime.backend is not None) == (memory_backend == EXPECTED_BACKEND), "Runtime Memory arm mismatch")
    try:
        await runtime.start_memory_backend()
        response = await runtime.agent_loop._process_message(
            TurnRequest(
                origin=Origin.USER,
                source=Source(
                    channel="installed-smoke",
                    chat_id=f"runtime-{memory_backend or 'off'}",
                    sender_id="user",
                    chat_type=ChatType.DM,
                ),
                text="Complete one installed Runtime Turn.",
            )
        )
        _require(response is not None, f"Runtime Turn failed for memory backend {memory_backend!r}")
    finally:
        await runtime.close()


async def _verified_learning_turn(repository: Path, backend: Any, *, index: int) -> None:
    from pico.agent.loop import AgentLoop
    from pico.spine.message import ChatType, Source
    from pico.spine.turn import Origin, TurnRequest

    agent = AgentLoop(
        provider=_VerifyingProvider(),
        workspace=repository,
        model="installed-smoke",
        max_iterations=3,
        restrict_to_workspace=True,
        backend=backend,
    )
    events: list[Any] = []

    async def emit(event: Any) -> None:
        events.append(event)

    outcome = await agent.run_turn(
        TurnRequest(
            origin=Origin.USER,
            source=Source(
                channel="installed-skill",
                chat_id=f"learning-{index}",
                sender_id="user",
                chat_type=ChatType.DM,
            ),
            text=SKILL_QUERY,
        ),
        emit,
        lambda: [],
        stream=False,
    )
    _require(outcome.explicit_reply, f"verified learning Turn {index} produced no reply")
    _require(outcome.tool_calls == 1, f"verified learning Turn {index} did not execute one check")
    _require(bool(events), f"verified learning Turn {index} was not delivered")


async def _learn(repository: Path, *, indexes: tuple[int, ...]) -> None:
    backend = _backend(repository)
    _require(backend is not None, "Skill learning backend was not constructed")
    await backend.start()
    try:
        for index in indexes:
            await _verified_learning_turn(repository, backend, index=index)
    finally:
        await backend.stop()


async def _skill_probe(repository: Path, state: Path, *, query: str) -> tuple[str, list[str]]:
    from pico.cli._runtime_assembly import assemble_runtime
    from pico.config.paths import RuntimePaths
    from pico.config.pico import MemoryConfig, PicoConfig
    from pico.config.schema import Config
    from pico.spine.message import ChatType, Source
    from pico.spine.turn import Origin, TurnRequest

    provider = _RecordingProvider()
    config = Config()
    config.agents.defaults.workspace = str(repository)
    config.agents.defaults.model = "installed-smoke"
    config.agents.defaults.enable_personalization = False
    config.routing.enabled = False
    pico_config = PicoConfig(memory=MemoryConfig(backend=EXPECTED_BACKEND))
    pico_config.base = config
    pico_config.skill_forge.rewrite_enabled = False
    pico_config.skill_forge.llm_gate_enabled = False
    runtime = assemble_runtime(
        config,
        pico_config,
        provider=provider,
        cron_service=None,
        interactive=False,
        paths=RuntimePaths(workspace=repository, state=state),
    )
    try:
        await runtime.start_memory_backend()
        recalled = await runtime.backend.recall(query, agent_id="pico", top_k=5) if runtime.backend is not None else []
        response = await runtime.agent_loop._process_message(
            TurnRequest(
                origin=Origin.USER,
                source=Source(
                    channel="installed-skill",
                    chat_id=hashlib.sha256(query.encode()).hexdigest()[:12],
                    sender_id="user",
                    chat_type=ChatType.DM,
                ),
                text=query,
            )
        )
        _require(response is not None, "Skill probe Turn produced no response")
    finally:
        await runtime.close()
    prompt = "\n".join(str(message.get("content")) for message in provider.messages)
    return prompt, [str(item.metadata.get("revision_id")) for item in recalled]


async def _store(repository: Path) -> None:
    from pico.agent.loop import AgentLoop
    from pico.spine.message import ChatType, Source
    from pico.spine.turn import Origin, TurnRequest

    backend = _backend(repository)
    _require(backend is not None, "Myna backend was not constructed")
    await backend.start()
    try:
        provider = _RecordingProvider()
        agent = AgentLoop(
            provider=provider,
            workspace=repository,
            model="installed-smoke",
            max_iterations=2,
            restrict_to_workspace=True,
            backend=backend,
        )
        response = await agent._process_message(
            TurnRequest(
                origin=Origin.USER,
                source=Source(
                    channel="installed-smoke",
                    chat_id="turn-one",
                    sender_id="user",
                    chat_type=ChatType.DM,
                ),
                text=f"Remember that {MEMORY_TEXT}",
            )
        )
        _require(response is not None, "store Turn produced no response")
    finally:
        await backend.stop()


async def _recall(repository: Path) -> dict[str, Any]:
    from pico.agent.loop import AgentLoop
    from pico.spine.message import ChatType, Source
    from pico.spine.turn import Origin, TurnRequest

    backend = _backend(repository)
    _require(backend is not None, "Myna backend was not constructed")
    await backend.start()
    try:
        hits = await backend.recall("How are Pico releases checked?", user_id="default", top_k=5)
        unrelated = await backend.recall(
            "cafeteria menu typography unrelated satellite telemetry",
            user_id="default",
            top_k=5,
        )
        agent_unrelated = await backend.recall(
            "cafeteria menu typography unrelated satellite telemetry",
            agent_id="pico",
            top_k=5,
        )
        provider = _RecordingProvider()
        agent = AgentLoop(
            provider=provider,
            workspace=repository,
            model="installed-smoke",
            max_iterations=2,
            restrict_to_workspace=True,
            backend=backend,
        )
        response = await agent._process_message(
            TurnRequest(
                origin=Origin.USER,
                source=Source(
                    channel="installed-smoke",
                    chat_id="turn-two",
                    sender_id="user",
                    chat_type=ChatType.DM,
                ),
                text="How are Pico releases checked?",
            )
        )
        _require(response is not None, "recall Turn produced no response")
    finally:
        await backend.stop()
    _require(len(hits) == 1, "relevant recall did not return exactly one compiled context")
    _require(unrelated == [], "unrelated query did not abstain")
    _require(agent_unrelated == [], "agent Skill hard negative did not abstain")
    source_uris = hits[0].metadata["source_uris"]
    _require(
        bool(source_uris) and all(uri.startswith("myna://") for uri in source_uris),
        "recall provenance is missing a myna:// source URI",
    )
    prompt = "\n".join(str(message.get("content")) for message in provider.messages)
    _require(MEMORY_TEXT in prompt, "before-Turn recall was not injected into the provider prompt")
    return {
        "text": hits[0].text,
        "source_uris": source_uris,
        "repo_key": hits[0].metadata["repo_key"],
        "unrelated": unrelated,
    }


def _assert_installed_identity(args: argparse.Namespace) -> None:
    import myna

    import pico

    source_root = args.source_root.resolve()
    myna_source_root = args.myna_source_root.resolve()
    _require(
        not Path(pico.__file__).resolve().is_relative_to(source_root),
        "Pico imported from the source checkout",
    )
    _require(
        not Path(myna.__file__).resolve().is_relative_to(myna_source_root),
        "Myna imported from the source checkout",
    )
    _require(metadata.version("pico-harness") == pico.__version__, "Pico package identity mismatch")
    _require(metadata.version("myna-memory") == EXPECTED_PLUGIN_VERSION, "Myna package version mismatch")
    _require(_sha256(args.myna_wheel) == args.myna_sha256, "Myna wheel digest mismatch")


def _assert_discovery_contract() -> None:
    from pico.config.pico import MemoryConfig, PicoConfig
    from pico.plugin import PluginDiscovery, PluginRegistry

    _require(PicoConfig().memory.backend == EXPECTED_BACKEND, "Myna is not the default backend")
    _require(MemoryConfig(backend=None).backend is None, "explicit Memory-off was not preserved")
    entry_points = [
        entry_point
        for entry_point in metadata.entry_points(group="pico.plugins")
        if getattr(getattr(entry_point, "dist", None), "name", None) == "myna-memory"
    ]
    _require(len(entry_points) == 1, "installed Myna distribution did not expose exactly one Pico entry point")
    _require(entry_points[0].name == "myna", "installed Myna entry-point name mismatch")
    _require(entry_points[0].value == "myna.integrations.pico", "installed Myna entry-point target mismatch")
    _require("myna.integrations.pico.app" not in sys.modules, "Myna App loaded before discovery")
    discovered = PluginDiscovery(entry_points_group="pico.plugins").discover()
    record = next(item for item in discovered if item.manifest.id == EXPECTED_PLUGIN_ID)
    manifest = record.manifest
    contribution = manifest.contributes.memory_backends[0]
    _require(manifest.version == EXPECTED_PLUGIN_VERSION, "Myna manifest version mismatch")
    _require(manifest.pico == EXPECTED_COMPATIBILITY, "Myna Pico compatibility mismatch")
    _require(contribution.name == EXPECTED_BACKEND, "Myna backend contribution mismatch")
    _require(contribution.factory == EXPECTED_FACTORY, "Myna backend factory mismatch")
    _require("myna.integrations.pico.app" not in sys.modules, "Myna App loaded during discovery")

    registry = PluginRegistry()
    registry.activate(discovered)
    _require(
        registry.memory_backend_identity(EXPECTED_BACKEND) == (EXPECTED_PLUGIN_ID, EXPECTED_FACTORY),
        "activated Myna identity mismatch",
    )
    _require("myna.integrations.pico.app" not in sys.modules, "Myna App loaded during activation")

    import myna.integrations.pico as integration

    _require("myna.integrations.pico.app" not in sys.modules, "Myna App loaded before descriptor use")
    descriptor = integration.descriptor()
    _require(descriptor.compatible_pico == EXPECTED_COMPATIBILITY, "Myna descriptor compatibility mismatch")
    _require("myna.integrations.pico.app" in sys.modules, "Myna App did not load on descriptor use")


def _assert_incompatible_plugin_is_transactional(root: Path) -> None:
    from pico.plugin import PluginCompatibilityError, PluginDiscovery, PluginRegistry

    manifest = root / "incompatible" / "pico-plugin.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        textwrap.dedent("""
            [plugin]
            id = "incompatible"
            version = "1.0.0"
            pico = ">=0.2,<0.3"
            enabled_by_default = true

            [[plugin.contributes.memory_backends]]
            name = "incompatible"
            factory = "does.not.exist:make_backend"
        """),
        encoding="utf-8",
    )
    registry = PluginRegistry()
    try:
        discovered = PluginDiscovery(bundled_dir=root, pico_version="0.1.7").discover()
        registry.activate(discovered)
    except PluginCompatibilityError as exc:
        _require("install a compatible plugin version" in str(exc), "incompatibility error is not actionable")
    else:
        raise AssertionError("incompatible plugin was admitted")
    _require(registry.activated_ids() == [], "incompatible plugin partially activated")
    _require(registry.memory_backend_names() == [], "incompatible backend partially registered")


async def _assert_fail_closed(repository: Path, runtime: Path, root: Path) -> None:
    from pico.cli._plugin_stack import MynaSetupError

    uninitialized = root / "uninitialized"
    uninitialized.mkdir()
    _git(uninitialized, "init", "-q")
    backend = _backend(uninitialized)
    _require(backend is not None, "uninitialized Myna backend was not constructed")
    try:
        await backend.start()
    except MynaSetupError as exc:
        _require("myna init" in str(exc), "uninitialized Myna error does not direct the operator to myna init")
    else:
        raise AssertionError("uninitialized Myna backend started")

    other = root / "other-repository"
    other.mkdir()
    _git(other, "init", "-q")
    embedded_runtime = other / ".myna"
    myna = Path(sys.executable).parent / "myna"
    subprocess.run(
        (
            str(myna),
            "init",
            "--root",
            str(embedded_runtime),
            "--repo-key",
            "example/pico-mismatch-smoke",
            "--retrieval-profile",
            "fastembed",
            "--semantic-profile",
            "none",
        ),
        cwd=other,
        check=True,
        capture_output=True,
        text=True,
    )
    mismatch = _backend(other)
    _require(mismatch is not None, "repository-mismatch Myna backend was not constructed")
    try:
        await mismatch.start()
    except Exception as exc:
        _require(
            getattr(exc, "code", None) == "myna_repository_mismatch",
            "repository mismatch returned the wrong error code",
        )
    else:
        raise AssertionError("repository mismatch was admitted")

    live = _backend(repository)
    _require(live is not None, "initialized Myna backend was not constructed")
    await live.start()
    try:
        before = set((runtime / "sources" / "pico").glob("*/*.jsonl"))
        await live.store("journal-failure", [{"role": "user", "content": "Create a journal for corruption testing."}])
    finally:
        await live.stop()
    created = set((runtime / "sources" / "pico").glob("*/*.jsonl")) - before
    _require(len(created) == 1, "journal fault setup did not create exactly one source")
    with next(iter(created)).open("ab") as handle:
        handle.write(b"unterminated")

    journal_backend = _backend(repository)
    _require(journal_backend is not None, "journal-failure Myna backend was not constructed")
    await journal_backend.start()
    try:
        try:
            await journal_backend.store("journal-failure", [{"role": "user", "content": "This must fail."}])
        except Exception as exc:
            _require(
                getattr(exc, "code", None) in {"pico_journal_invalid", "source_rewritten", "myna_store_failed"},
                "journal failure returned the wrong error code",
            )
        else:
            raise AssertionError("journal failure was swallowed")
    finally:
        await journal_backend.stop()

    with sqlite3.connect(runtime / "state.sqlite3") as connection:
        updated = connection.execute(
            "UPDATE index_jobs SET status = 'failed', attempt_count = 3 WHERE status = 'indexed'"
        ).rowcount
    _require(updated > 0, "index fault setup found no completed index job")
    index_backend = _backend(repository)
    _require(index_backend is not None, "index-failure Myna backend was not constructed")
    try:
        await index_backend.start()
    except Exception as exc:
        _require(getattr(exc, "code", None) == "index_not_ready", "failed index returned the wrong error code")
    else:
        raise AssertionError("failed index was admitted")


def _child(args: argparse.Namespace) -> int:
    if args.repository is None:
        raise SystemExit("--repository is required with --phase")
    _assert_installed_identity(args)
    if args.phase == "store":
        asyncio.run(_store(args.repository))
        print(json.dumps({"stored": True}, sort_keys=True))
    else:
        print(json.dumps(asyncio.run(_recall(args.repository)), sort_keys=True))
    return 0


def _clean_environment(home: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment.update(
        {
            "HOME": str(home),
            "PICO_HOME": str(home / "pico"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def _assert_cli_identity(repository: Path, home: Path) -> None:
    from pico.config.loader import save_config, set_config_path
    from pico.config.schema import Config

    config_path = home / "pico" / "config.json"
    set_config_path(config_path)
    config = Config()
    config.agents.defaults.model = "anthropic/claude-sonnet-4-5"
    config.agents.defaults.workspace = str(repository)
    config.providers.anthropic.api_key = "installed-smoke"
    save_config(config)
    set_config_path(None)

    environment = _clean_environment(home)
    executable = Path(sys.executable).parent / "pico"
    version = subprocess.run(
        (str(executable), "--version"),
        cwd=repository,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    _require(metadata.version("pico-harness") in version.stdout, "pico --version reported the wrong package version")
    doctor = subprocess.run(
        (str(executable), "doctor", "--json"),
        cwd=repository,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(doctor.stdout)
    _require(
        report["memory"]
        == {
            "backend": EXPECTED_BACKEND,
            "state": "available",
            "plugin_id": EXPECTED_PLUGIN_ID,
            "plugin_version": EXPECTED_PLUGIN_VERSION,
            "error": None,
        },
        "pico doctor did not report the installed Myna plugin as available",
    )


def _assert_turn_feedback(runtime: Path) -> None:
    """确认安装态 Pico feedback 已被 Myna 绑定为内容寻址 Turn Evidence。"""
    with sqlite3.connect(runtime / "state.sqlite3") as connection:
        rows = connection.execute(
            "SELECT experience_id, canonical_evidence_json FROM pico_turn_evidence ORDER BY session_id, turn_id"
        ).fetchall()
    _require(bool(rows), "installed Pico Turn feedback was not persisted by Myna")
    decoded = [(experience_id, json.loads(encoded)) for experience_id, encoded in rows]
    _require(all(item[0].startswith("mem_") for item in decoded), "Turn Evidence is not bound to Task Experience")
    _require(
        all(item[1].get("schema") == "pico.turn-evidence.v1" for item in decoded),
        "installed Turn Evidence schema mismatch",
    )
    _require(
        any(item[1].get("session_id") == "installed-smoke:turn-one" for item in decoded),
        "fresh-process store has no matching Turn Evidence",
    )


def _draft_revision_ids(report: dict[str, Any]) -> list[str]:
    draft_ids = {
        str(event["revision_id"])
        for event in report.get("lifecycle", [])
        if event.get("from_status") is None and event.get("to_status") == "draft"
    }
    return sorted(
        str(item["revision"]["revision_id"])
        for item in report.get("revisions", [])
        if item.get("revision", {}).get("revision_id") in draft_ids
    )


def _initialize_skill_repository(repository: Path, runtime: Path, environment: dict[str, str]) -> None:
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "installed-smoke@example.invalid")
    _git(repository, "config", "user.name", "Installed Smoke")
    (repository / "Makefile").write_text(".PHONY: check\ncheck:\n\t@true\n", encoding="utf-8")
    _git(repository, "add", "Makefile")
    _git(repository, "commit", "-qm", "test: add deterministic verifier")
    _myna_cli(
        repository,
        environment,
        "init",
        "--root",
        str(runtime),
        "--repo-key",
        "example/pico-skill-evolution-smoke",
        "--retrieval-profile",
        "fastembed",
        "--semantic-profile",
        "openai-compatible",
    )


def _assert_skill_evolution(root: Path) -> dict[str, Any]:
    repository = root / "skill-repository"
    runtime = root / "skill-runtime"
    with _semantic_server(root) as (endpoint, certificate):
        environment = _clean_environment(root / "skill-home")
        semantic_environment = {
            "MYNA_SEMANTIC_API_KEY": "installed-smoke",
            "MYNA_SEMANTIC_ENDPOINT": endpoint,
            "MYNA_SEMANTIC_MODEL": "installed-smoke",
            "SSL_CERT_FILE": str(certificate),
        }
        environment.update(semantic_environment)
        with _temporary_environment(semantic_environment):
            _initialize_skill_repository(repository, runtime, environment)
            asyncio.run(_learn(repository, indexes=(1, 2, 3)))

            first_report = _myna_cli_json(repository, environment, "skill", "list")
            first_drafts = _draft_revision_ids(first_report)
            _require(len(first_drafts) == 1, "three verified Turns did not create exactly one draft Skill")
            first_revision = first_drafts[0]
            first_activation = _myna_cli_json(
                repository,
                environment,
                "skill",
                "activate",
                first_revision,
                "--authority",
                "evaluation",
                "--receipt-id",
                "installed-skill-e2e-v1-first",
            )
            _require(
                first_activation["revision_id"] == first_revision, "first Skill activation selected the wrong revision"
            )

            relevant_prompt, relevant_revisions = asyncio.run(
                _skill_probe(repository, root / "skill-probe-first", query=SKILL_QUERY)
            )
            negative_prompt, negative_revisions = asyncio.run(
                _skill_probe(
                    repository, root / "skill-probe-negative", query="cafeteria typography satellite telemetry"
                )
            )
            _require(relevant_revisions == [first_revision], "active Skill was not recalled from the installed backend")
            _require(SKILL_PROCEDURE in relevant_prompt, "active Skill was not injected into the installed Pico prompt")
            _require(negative_revisions == [], "agent Skill recall did not abstain on the hard negative")
            _require(SKILL_PROCEDURE not in negative_prompt, "hard negative injected the active Skill into Pico")

            asyncio.run(_learn(repository, indexes=(4,)))
            second_report = _myna_cli_json(repository, environment, "skill", "list")
            second_drafts = [revision for revision in _draft_revision_ids(second_report) if revision != first_revision]
            _require(len(second_drafts) == 1, "a fourth verified Turn did not create one successor draft")
            second_revision = second_drafts[0]
            second_activation = _myna_cli_json(
                repository,
                environment,
                "skill",
                "activate",
                second_revision,
                "--authority",
                "evaluation",
                "--receipt-id",
                "installed-skill-e2e-v1-second",
            )
            _require(
                second_activation["revision_id"] == second_revision, "successor activation selected the wrong revision"
            )
            rollback = _myna_cli_json(
                repository,
                environment,
                "skill",
                "rollback",
                first_revision,
                "--authority",
                "evaluation",
                "--receipt-id",
                "installed-skill-e2e-v1-rollback",
            )
            _require(rollback["revision_id"] == first_revision, "rollback did not restore the first accepted revision")
            rejected = _myna_cli_json(
                repository,
                environment,
                "skill",
                "reject",
                second_revision,
                "--authority",
                "evaluation",
                "--receipt-id",
                "installed-skill-e2e-v1-reject",
            )
            _require(rejected["to_status"] == "rejected", "superseded revision rejection was not recorded")

            restarted_prompt, restarted_revisions = asyncio.run(
                _skill_probe(repository, root / "skill-probe-restart", query=SKILL_QUERY)
            )
            _require(restarted_revisions == [first_revision], "rollback did not survive an installed backend restart")
            _require(SKILL_PROCEDURE in restarted_prompt, "restarted Pico did not inject the rolled-back Skill")
            denied = _myna_cli(
                repository,
                environment,
                "skill",
                "activate",
                second_revision,
                "--authority",
                "evaluation",
                "--receipt-id",
                "installed-skill-e2e-v1-denied",
                check=False,
            )
            _require(denied.returncode != 0, "rejected Skill revision was reactivated")
            _require(_SemanticHandler.skill_requests == 2, "Skill extraction did not use exactly two eligible groups")
    return {
        "drafts_created": 2,
        "hard_negative_abstained": True,
        "installed_prompt_injection": True,
        "rejected_reactivation_denied": True,
        "rollback_survived_restart": True,
    }


def main() -> int:
    args = _parser().parse_args()
    if args.phase:
        return _child(args)
    _assert_installed_identity(args)
    _assert_discovery_contract()

    with tempfile.TemporaryDirectory(prefix="pico-myna-installed-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        repository.mkdir()
        _git(repository, "init", "-q")
        runtime = root / "myna-runtime"
        myna = Path(sys.executable).parent / "myna"
        subprocess.run(
            (
                str(myna),
                "init",
                "--root",
                str(runtime),
                "--repo-key",
                "example/pico-installed-smoke",
                "--retrieval-profile",
                "fastembed",
                "--semantic-profile",
                "none",
            ),
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        asyncio.run(_runtime_turn(repository, root / "memory-off-state", memory_backend=None))
        asyncio.run(_runtime_turn(repository, root / "memory-on-state", memory_backend=EXPECTED_BACKEND))
        _assert_incompatible_plugin_is_transactional(root / "plugins")
        common = (
            str(Path(__file__).resolve()),
            "--pico-wheel",
            str(args.pico_wheel),
            "--myna-wheel",
            str(args.myna_wheel),
            "--source-root",
            str(args.source_root),
            "--myna-source-root",
            str(args.myna_source_root),
            "--myna-sha256",
            args.myna_sha256,
            "--repository",
            str(repository),
        )
        environment = _clean_environment(root / "home")
        _assert_cli_identity(repository, root / "home")
        store = subprocess.run(
            (sys.executable, *common, "--phase", "store"),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        recall = subprocess.run(
            (sys.executable, *common, "--phase", "recall"),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        recalled = json.loads(recall.stdout.splitlines()[-1])
        _require(json.loads(store.stdout.splitlines()[-1]) == {"stored": True}, "store child did not complete")
        _assert_turn_feedback(runtime)
        _require(bool(recalled["source_uris"]), "fresh-process recall has no provenance")
        asyncio.run(_assert_fail_closed(repository, runtime, root))
        skill_evolution = _assert_skill_evolution(root)

    print(
        json.dumps(
            {
                "backend": EXPECTED_BACKEND,
                "factory": EXPECTED_FACTORY,
                "fresh_process_recall": True,
                "turn_feedback_persisted": True,
                "myna_wheel_sha256": args.myna_sha256,
                "plugin_id": EXPECTED_PLUGIN_ID,
                "plugin_version": EXPECTED_PLUGIN_VERSION,
                "runtime_memory_off": True,
                "runtime_memory_on": True,
                "skill_evolution": skill_evolution,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
