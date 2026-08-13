from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
from importlib import metadata
from pathlib import Path
from typing import Any

EXPECTED_PLUGIN_ID = "myna-memory"
EXPECTED_PLUGIN_VERSION = "0.1.1rc3"
EXPECTED_COMPATIBILITY = ">=0.1,<0.2"
EXPECTED_BACKEND = "myna"
EXPECTED_FACTORY = "myna.integrations.pico:make_backend"
MEMORY_TEXT = "Pico releases require make check."


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
        _require(bool(recalled["source_uris"]), "fresh-process recall has no provenance")
        asyncio.run(_assert_fail_closed(repository, runtime, root))

    print(
        json.dumps(
            {
                "backend": EXPECTED_BACKEND,
                "factory": EXPECTED_FACTORY,
                "fresh_process_recall": True,
                "myna_wheel_sha256": args.myna_sha256,
                "plugin_id": EXPECTED_PLUGIN_ID,
                "plugin_version": EXPECTED_PLUGIN_VERSION,
                "runtime_memory_off": True,
                "runtime_memory_on": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
