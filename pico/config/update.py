"""Minimal in-place updates for ~/.pico/config.json.

Unlike ``save_config`` which re-serializes the entire Pydantic model (and
would bake every runtime default back into the file), these helpers read
the raw JSON, patch a small set of fields, and atomically rewrite via
temp-file + rename. Used by ``pico cron config set`` and the
onboarding wizard so the change persists across restarts without
touching unrelated fields.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic.alias_generators import to_camel

from pico.config.loader import get_config_path, read_raw_or_raise
from pico.config.schema import CronConfig


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def update_cron_config(
    key: str,
    value: Any,
    *,
    config_path: Path | None = None,
) -> Any:
    """Patch a single CronConfig field on-disk.

    Returns the previous raw value (None if absent). Raises ``KeyError`` if
    ``key`` is not a CronConfig field — defensive only; CLI ``_KEY_HANDLERS``
    already validates before reaching here. Type validation of ``value`` is
    the caller's responsibility (CLI parsers handle it).
    """
    if key not in CronConfig.model_fields:
        raise KeyError(f"Unknown cron config key: {key!r}. Supported: {sorted(CronConfig.model_fields)}")
    path = config_path or get_config_path()
    data = read_raw_or_raise(path)
    cron_section = data.setdefault("cron", {})
    camel_key = to_camel(key)
    prev = cron_section.get(camel_key)
    cron_section[camel_key] = value
    _write_atomic(path, data)
    logger.info("config/update: cron.{} set to {!r} (was {!r})", key, value, prev)
    return prev


def reset_cron_config(*, config_path: Path | None = None) -> None:
    """Remove the entire ``cron`` section from on-disk config.

    Schema defaults (``forward_channels=["*"]`` / ``default_timezone="Asia/Shanghai"``)
    take effect on next load. Stays consistent with the file's "never bake
    defaults to disk" principle.
    """
    path = config_path or get_config_path()
    data = read_raw_or_raise(path)
    removed = data.pop("cron", None)
    _write_atomic(path, data)
    logger.info("config/update: cron section reset (was {!r})", removed)


def set_language(
    language: str,
    *,
    config_path: Path | None = None,
) -> str | None:
    """Patch the top-level ``language`` on the on-disk config. Returns previous value.

    Set by the onboarding wizard's language screen. Read by the CLI/wizard copy
    (via ``_t``) and injected into the agent's system prompt so replies use the
    chosen language.
    """
    path = config_path or get_config_path()
    data = read_raw_or_raise(path)
    prev = data.get("language")
    data["language"] = language
    _write_atomic(path, data)
    logger.info("config/update: language set to {!r} (was {!r})", language, prev)
    return prev


def set_default_model(
    model: str,
    *,
    config_path: Path | None = None,
) -> str | None:
    """Patch ``agents.defaults.model`` on the on-disk config. Returns previous value.

    Used by the onboarding wizard after the user picks a provider: the wizard
    needs to swap the default model to one that matches the chosen provider
    (otherwise ``pico run`` would still route to whatever the freshly
    created ``Config()`` baked in, which is typically a different vendor).
    """
    path = config_path or get_config_path()
    data = read_raw_or_raise(path)
    defaults = data.setdefault("agents", {}).setdefault("defaults", {})
    prev = defaults.get("model")
    defaults["model"] = model
    _write_atomic(path, data)
    logger.info("config/update: default model set to {} (was {})", model, prev)
    return prev


def set_sandbox_backend(
    backend: str,
    *,
    config_path: Path | None = None,
) -> str | None:
    """Patch ``sandbox.backend`` on the on-disk config. Returns previous value.

    Used by the onboarding wizard's run-location step. ``backend`` must be one
    of ``SandboxConfig``'s literal values (``none`` / ``auto`` / ``boxlite``);
    the loader validates on next read.
    """
    path = config_path or get_config_path()
    data = read_raw_or_raise(path)
    # sandbox lives under tools (Config.tools.sandbox), not at the root — the
    # root Config forbids extras, so a top-level "sandbox" key fails schema
    # validation on the next load.
    section = data.setdefault("tools", {}).setdefault("sandbox", {})
    prev = section.get("backend")
    section["backend"] = backend
    _write_atomic(path, data)
    logger.info("config/update: tools.sandbox.backend set to {!r} (was {!r})", backend, prev)
    return prev


def init_extension_block_defaults(*, config_path: Path | None = None) -> None:
    """Seed the user-facing subset of the memory / plugins / skillForge
    extension blocks into a fresh ``~/.pico/config.json``.

    Called once by the onboarding bootstrap so a new config shows these knobs
    at their schema defaults — discoverable and editable without reading the
    source. Each field is only written when absent (``setdefault``), so this is
    idempotent and never clobbers a value the user (or an earlier wizard step)
    already set. ``memory.backend`` is seeded to its schema default
    (``"codecairn"``). The onboarding flow keeps that selection and directs
    operators to initialize CodeCairn in the configured Workspace.

    Defaults are pulled from the Pydantic models so this seed can't drift from
    the schema. Plugin configuration stays empty because CodeCairn owns
    repository, profile, runtime-root, and credential selection.

    The optional service fields on ``SkillForgeConfig`` (``embedding_url`` /
    ``embedding_api_key`` / ``reranker_url`` / ``reranker_api_key`` /
    ``mass_library_db``) are deliberately NOT written. They stay at public
    schema defaults and deployments that need hosted services add explicit
    values by hand.

    Key casing follows each block's convention: ``memory`` / ``skillForge`` use
    camelCase (the file-level alias); ``plugins.config`` is a verbatim
    pass-through dict whose keys stay snake_case (each plugin owns its schema).
    """
    from pico.config.pico import (
        MemoryConfig,
        PluginsConfig,
        SkillForgeRouterConfig,
    )

    path = config_path or get_config_path()
    data = read_raw_or_raise(path)

    mem = MemoryConfig()
    memory = data.setdefault("memory", {})
    memory.setdefault("backend", mem.backend)
    memory.setdefault("userId", mem.user_id)
    memory.setdefault("memoryTopK", mem.memory_top_k)

    plugins = data.setdefault("plugins", {})
    plugins.setdefault("disabled", list(PluginsConfig().disabled))
    plugins.setdefault("config", {})

    router_defaults = SkillForgeRouterConfig()
    skill_forge = data.setdefault("skillForge", {})
    skill_forge.setdefault("enabled", True)
    router = skill_forge.setdefault("router", {})
    router.setdefault("enabled", router_defaults.enabled)

    _write_atomic(path, data)
    logger.info("config/update: seeded memory/plugins/skillForge extension defaults")


def set_memory_backend(
    backend: str | None,
    *,
    config_path: Path | None = None,
) -> str | None:
    """Patch ``memory.backend`` on the on-disk config. Returns previous value.

    ``"codecairn"`` selects repository Memory; ``None`` disables implicit
    Memory while preserving Sessions and Local Skills.
    """
    path = config_path or get_config_path()
    data = read_raw_or_raise(path)
    section = data.setdefault("memory", {})
    prev = section.get("backend")
    section["backend"] = backend
    _write_atomic(path, data)
    logger.info("config/update: memory.backend set to {!r} (was {!r})", backend, prev)
    return prev


__all__ = [
    "update_cron_config",
    "reset_cron_config",
    "set_default_model",
    "set_sandbox_backend",
    "set_memory_backend",
    "init_extension_block_defaults",
]
