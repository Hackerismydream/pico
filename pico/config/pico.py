"""Pico feature configuration - extends the base Config with feature blocks.

Usage:
    from pico.config import PicoConfig, load_pico_config

    cfg = load_pico_config()
    if cfg.context.engine == "curator":
        ...

Design:
    - ``PicoConfig`` composes the base ``Config`` rather than subclassing
      it. This keeps the base schema untouched and lets us add / remove
      feature blocks without breaking the base loader.
    - Each feature block has its own Pydantic model. Defaults are
      conservative: every novel feature starts OFF so a fresh install behaves
      like the base agent until features are enabled.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from pico.config.loader import (
    EXTENSION_KEYS,
    _migrate_config,
    get_config_path,
)
from pico.config.loader import load_config as load_base_config
from pico.config.schema import Config as BaseConfig


class _Base(BaseModel):
    """Accepts both camelCase and snake_case keys.

    ``extra='forbid'`` catches typos at startup. Retired fields with
    known legacy presence are stripped explicitly in
    ``loader._migrate_config`` before Pydantic validates; unlisted
    unknown keys still raise.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


# ---------------------------------------------------------------------------
# Feature 1 — Context Management (Curator)
# ---------------------------------------------------------------------------


class ContextConfig(_Base):
    """Context engine selection and tuning."""

    engine: str = "unified"
    """Deprecated — there is now a single :class:`ContextAssembler`.

    The historical ``"legacy"`` / ``"curator"`` / ``"default"`` split was
    collapsed: every turn runs the Curator history, Memory, and Local Skill
    lanes in one engine. The field is retained (as a
    free string) so existing YAML setting ``engine: legacy`` etc. still
    loads — the value is ignored by ``build_context_engine``.
    """

    # Curator history-lane knobs.
    fast_path_threshold: float = 0.60
    """Curator Fast Path cutoff. Below this % of budget → zero-LLM pass-through."""

    curator_model: str = "gemini-2.5-flash"
    """Model used by the Curator agent loop (Slow Path). Kept small & fast."""

    curator_timeout_seconds: float = 30.0
    """Max wall time for one Curator slow-path invocation before fallback."""

    relevance_decay: float = 0.95
    """Per-turn decay factor for non-recent message relevance."""

    relevance_reference_boost: float = 0.15
    """Boost applied when assistant response references older message content."""

    protect_first_n: int = 3
    """Number of head exchanges always preserved in context."""

    archive_dir: str = "memory/.curator/archive"
    """Relative path under workspace for lossless message archives."""


# Feature 2 — Token Efficiency (TokenWise)
# ---------------------------------------------------------------------------


class BudgetPolicyConfig(_Base):
    """Per-session / per-day spend limits."""

    warn_at_usd: float = 0.50
    hard_limit_usd: float = 2.00
    warn_at_input_tokens: int = 500_000
    track_per_session: bool = True
    track_global_daily: bool = True


class SmartRoutingConfig(_Base):
    """SmartRouter configuration."""

    enabled: bool = False
    tiers: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "light": ["gemini-2.5-flash", "claude-haiku-4-5"],
            "medium": ["claude-sonnet-4-6", "gpt-4.1-mini"],
            "heavy": ["claude-opus-4-6", "gpt-4.1"],
        }
    )
    default_tier: Literal["light", "medium", "heavy"] = "heavy"
    """Fallback tier when routing is uncertain — conservative default."""


class ToolResultLifecycleConfig(_Base):
    """Tool result lifecycle management (the three-phase pruner)."""

    enabled: bool = False
    full_retention_turns: int = 3
    summary_retention_turns: int = 10
    placeholder_text: str = "[Tool result archived — retrievable via Curator]"
    summary_model: str = "gemini-2.5-flash"


class TokenWiseConfig(_Base):
    """TokenWise cross-cutting token/cost optimization."""

    enabled: bool = True
    """Master switch. Disabling skips all strategies."""

    usage_tracking: bool = True
    """Record token usage per call — cheap and informative; on by default."""

    cache_optimization: bool = True
    """Apply Anthropic cache_control breakpoints. No-op on other providers."""

    max_cache_breakpoints: int = 4
    """Anthropic API limit; kept configurable for forward-compat."""

    skill_lazy_loading: bool = False
    """Only inject skill summaries relevant to the current message."""

    tool_result_lifecycle: ToolResultLifecycleConfig = Field(default_factory=ToolResultLifecycleConfig)
    smart_routing: SmartRoutingConfig = Field(default_factory=SmartRoutingConfig)
    budget: BudgetPolicyConfig = Field(default_factory=BudgetPolicyConfig)


# ---------------------------------------------------------------------------
# Feature 3 — SkillForge
# ---------------------------------------------------------------------------
#
# SkillForge owns Local Skill retrieval and execution.
#
# The config is intentionally kept flat. Component-level knobs
# (embedding model, BM25 parameters, etc.) live in the
# scaffold dataclasses inside ``skill_forge/`` and stay at their
# defaults for now. Owners will promote individual fields here when
# they need user-facing knobs.


class LocalDirConfig(_Base):
    """One local skill directory entry (R1)."""

    path: str
    """Absolute or ``~``-relative path. Expanded at startup."""

    enabled: bool = True
    """False → directory completely skipped."""

    name: str | None = None
    """Display name for logs. None → derived from path basename."""

    always_enabled: bool = True
    """False → skills from this dir with ``always: true`` are excluded
    from always injection (but still retrievable via select)."""


class SkillForgeConfig(_Base):
    """SkillForge configuration.

    ``enabled=True`` (default, R8) activates the SkillForge retrieval/
    injection pipeline. Set ``enabled=False`` to fall back to the
    pre-refactor behavior of handing the full skill directory to the LLM
    (component stubs that return empty lists also cause ``ContextBuilder``
    to fall back to the full directory automatically).

    Repository Memory is independent of this subsystem. SkillForge retrieves
    only operator-managed Local Skills.
    """

    # --- Master switch + location ---
    enabled: bool = True
    """Master switch (R8: default True). Activates the SkillForge
    retrieval/injection pipeline."""

    router: "SkillForgeRouterConfig" = Field(
        default_factory=lambda: SkillForgeRouterConfig(),
    )
    """Local BM25 routing policy, under config key ``skillForge.router``. The
    router is a component of the SkillForge subsystem, so it nests here
    rather than living as a sibling top-level block. Forward-ref +
    ``model_rebuild`` (below): ``SkillForgeRouterConfig`` is defined later
    in this module."""

    local_dirs: list[LocalDirConfig] = Field(default_factory=list)
    """Local skill directories to mount (R1). List order = priority:
    later entries override earlier on name collision. Legacy
    ``skills_dir`` auto-migrated via model_validator (R5)."""

    scan_max_depth: int = 5
    """Maximum directory depth when scanning for SKILL.md files (R2).
    Paths deeper than this below a layer root are silently skipped.
    Prevents unbounded filesystem walks on huge mirrors."""

    # --- Retrieval / reranker knobs ---
    embedding_model: str = "default"
    """Dense embedding model identifier. MUST match the embedding model
    that produced ``mass_library_db``'s stored vectors, otherwise dense
    retrieval returns garbage because the query vector lives in a different
    space. Configure this to match the embedding service and corpus used by
    your deployment."""

    embedding_url: str = "http://localhost:1357"
    """Remote embedding service base URL.

    Retrieval calls ``POST <embedding_url>/embed``. Override this with
    ``REMOTE_EMBEDDING_URL`` or user config when using a hosted embedding
    service."""

    reranker_enabled: bool = True
    """Run a reranker pass after dense retrieval. On by default — adds
    200-500ms per query (cross-encoder GPU inference) but lifts mass-pool
    precision noticeably. Disable when latency matters more than ranking."""

    reranker_model: str = "default"
    """Reranker model label used for configuration and observability."""

    reranker_url: str = "http://localhost:1357"
    """Remote reranker service base URL.

    Reranking calls ``POST <reranker_url>/score`` with
    ``{"prompts": [...]}`` and reads ``{"scores": [...]}``. Override this
    with ``REMOTE_RERANKER_URL`` or user config when using a hosted reranker
    service."""

    embedding_api_key: str | None = None
    """Optional bearer token for the configured embedding service."""

    reranker_api_key: str | None = None
    """Optional bearer token for the configured reranker service."""

    embedding_dimensions: int | None = None
    """Request specific embedding dimensions (for models that support it)."""

    top_k: int = 5
    """Number of skills returned by ``select()``."""

    # --- Dual-pool fusion weights (R6) ---
    local_pool_top_k: int = 10
    """Candidate count from the local BM25 pool per query."""

    mass_pool_top_k: int = 10
    """Candidate count from the mass dense pool per query (post-rerank)."""

    local_weight: float = 1.3
    """RRF weight for local-pool candidates (mass is implicitly 1.0).
    Recommended range [1.2, 1.5]. Values < 1.0 or > 2.0 are rejected."""

    mass_reranker_overfetch: int = 20
    """When reranker is enabled, mass pool fetches this many candidates
    for rescoring, then truncates to ``mass_pool_top_k`` before RRF."""

    # --- Query rewrite knobs ---
    rewrite_enabled: bool = True
    """Enable a second retrieval path with LLM-rewritten queries."""

    rewrite_max_tokens: int = 8192
    """Output token budget for the rewriter LLM call. Defaults to 8192 to
    leave headroom for Qwen3-style reasoning traces (~3-4k tokens) on top
    of the actual rewrite output. The previous 1024 budget caused frequent
    finish_reason=length truncations with empty visible content, which
    surfaced as 'Failed to parse rewrite response as JSON' fallbacks."""

    mass_library_db: str | None = None
    """Deprecated compatibility field ignored by Local Skill retrieval."""

    # --- Skill injection mode (full_body vs summary) ---
    injection_mode: str = "full_body"
    """How selected skills are surfaced to the agent.

    - ``"full_body"`` (default, OpenSpace style): load_skills_for_context
      inlines the full SKILL.md body of up to ``inject_max`` LLM-gate-
      selected candidates into the system prompt. Higher token cost but
      guarantees content visibility. Pairs with ``llm_gate_enabled=True``
      below — the gate cuts a 15-skill candidate pool down to ~2 truly
      relevant ones, so per-turn token cost stays bounded (~2-10K).
    - ``"summary"``: build_skills_summary renders an XML directory of
      (name, description, available) tuples. Agent must call ``read_file``
      on a skill's SKILL.md to access its body — progressive disclosure,
      cheaper in tokens but Round-D eval showed agents often skip the
      read step entirely (top1_kw rate ~0.62 vs ~0.80 with full_body)."""

    inject_max: int = 2
    """Max skills inlined when ``injection_mode='full_body'``. Each skill body
    typically adds 1-5K tokens."""

    disable_always: bool = False
    """When True, ``get_always_skills()`` returns [] and select() filters
    out always:true skills. R8 default: False (always skills inject)."""

    always_max: int = 5
    """Max always skills injected per turn (R3). Exceeding this truncates
    by local_dirs list order + alphabetical, with a WARN listing dropped
    skill names."""

    # --- LLM gate selector (default-on, mirrors openspace select_skills_with_llm) ---
    llm_gate_enabled: bool = True
    """When ``True`` (default), ``select()`` resolves a pool of
    ``llm_gate_pool_size`` candidates after RRF merge, then asks an LLM to
    plan + filter down to ``llm_gate_max_select`` skills. Empty result is
    valid ("inject nothing"). Costs one LLM call per ``select()`` invocation
    but eliminates the ~30% noise-injection rate of pure-RRF top-K (Round D
    obs.: irrelevant skills polluting the prompt). Disable to skip the
    extra LLM call (rare; useful when LLM provider is unavailable)."""

    llm_gate_max_select: int = 2
    """Upper bound on skills the gate may select. Mirrors ``inject_max``."""

    llm_gate_pool_size: int = 10
    """Candidate pool size handed to the gate (after RRF). Aligned
    with RRF output size (local_pool_top_k + mass_pool_top_k dedupe)."""

    llm_gate_model: str | None = None
    """Optional model override for gate calls. ``None`` → use the
    provider's default chat model (typically the agent's main model)."""

    llm_gate_temperature: float = 0.0
    """Sampling temperature for gate calls. 0.0 for deterministic
    filtering. Reasoning models may need 0.6 to engage <think>."""

    llm_gate_max_tokens: int = 8192
    """Output token budget for the gate LLM call. Defaults to 8192 to
    leave headroom for Qwen3-style reasoning traces (~3-4k tokens) on top
    of the gate's JSON answer. The previous 4096 budget caused empty
    content (finish_reason=length) on the 27B model in ~50% of calls,
    forcing a legacy top-N fallback that returned 5 skills instead of
    the configured llm_gate_max_select."""

    stats_tracking: bool = True
    """Record per-skill invocation stats. Cheap, enables future features."""

    # --- Validators ---

    @model_validator(mode="before")
    @classmethod
    def _migrate_skills_dir(cls, data: dict) -> dict:
        """R5: auto-convert legacy ``skills_dir`` → ``local_dirs``."""
        if not isinstance(data, dict):
            return data
        for old_key in ("skills_dir", "skillsDir"):
            old_val = data.pop(old_key, None)
            if old_val and "local_dirs" not in data and "localDirs" not in data:
                data["local_dirs"] = [{"path": old_val}]
                warnings.warn(
                    f"skill_forge.{old_key} is deprecated, use local_dirs "
                    f"instead. Auto-converted to local_dirs=[{{path: {old_val!r}}}]. "
                    f"This field will be removed in a future release.",
                    DeprecationWarning,
                    stacklevel=2,
                )
        lw = data.get("local_weight") or data.get("localWeight")
        if lw is not None:
            lw = float(lw)
            if lw < 1.0 or lw > 2.0:
                raise ValueError(f"local_weight={lw} out of valid range [1.0, 2.0]")
        return data


# ---------------------------------------------------------------------------
# CFG-1 — Plugin / Memory backend / SkillForgeRouter
# ---------------------------------------------------------------------------


class PluginsConfig(_Base):
    """Plugin-system top-level config.

    ``disabled`` is the user opt-out list keyed by plugin id (matches
    the ``id`` in ``pico-plugin.toml``). ``config`` is the per-
    plugin config slice the registry hands to each plugin's factory
    via :class:`PluginContext.config` — its shape is determined by
    each plugin's own ``config_schema`` in the manifest, so the host
    treats it as a free-form dict.
    """

    disabled: list[str] = Field(default_factory=list)
    """Plugin ids the user opted out of."""

    config: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per-plugin configuration, keyed by plugin id. Each plugin's
    factory receives ``ctx.config = plugins.config.get(<id>, {})``."""


class MemoryConfig(_Base):
    """Which Memory backend is active and how recall is requested.

    ``backend`` is the name of an activated ``memory_backend``
    contribution. Set it to ``None`` to disable implicit Memory recall,
    persistence, personalization, and Curator Memory tools.

    ``user_id`` is the public Interface identity passed on the user recall
    track. CodeCairn binds Memory by Workspace repository and does not use it
    as a repository namespace.
    """

    backend: str | None = "codecairn"
    """Activated backend contribution name. ``None`` disables the
    implicit Memory path while preserving Sessions, Curator state, and
    Local Skills."""

    user_id: str = "default"
    """Bare user identity passed as ``backend.recall(user_id=...)`` for
    the user-track recall channel inside ``ContextAssembler.assemble``."""

    memory_top_k: int = 5
    """Top-K passed to ``backend.recall(user_id=user_id)`` per turn for
    the ``# Recalled memory`` block."""


class SkillForgeRouterConfig(_Base):
    """Local Skill BM25 routing policy."""

    enabled: bool = True
    """Master switch. ``False`` makes the host bypass SkillForgeRouter
    entirely (used by tests / restricted deployments)."""

    local_min_score: float = Field(
        default=0.0,
        ge=0.0,
        allow_inf_nan=False,
    )
    """Minimum BM25 score emitted by the Local skill source."""

    @field_validator("local_min_score", mode="before")
    @classmethod
    def _reject_boolean_local_min_score(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("local_min_score must be a number")
        return value

    top_k: int = 5
    """Final top-K returned from ``SkillForgeRouter.select``."""


# Resolve the forward-ref ``SkillForgeConfig.router: "SkillForgeRouterConfig"``
# now that ``SkillForgeRouterConfig`` exists in module scope.
SkillForgeConfig.model_rebuild()


# ---------------------------------------------------------------------------
# Feature 4 — Runtime Discipline
# ---------------------------------------------------------------------------


class CheckpointConfig(_Base):
    """Per-turn shadow-git checkpoint of the workspace.

    When active, the agent loop commits the workspace to an out-of-band
    shadow git repo at the end of each turn (covering both normal and
    max-iteration exits). This is the safety net behind Bug2: a truncated
    multi-file edit leaves a recoverable snapshot, and the next turn gets a
    recovery prompt listing what the interrupted turn changed.

    Activation is gated by ``policy`` and the AgentLoop's ``interactive``
    flag (set per call site by the CLI / TUI / gateway entry points):

    - ``"always"``     — active in every AgentLoop, including ``-m``
                          one-shot commands.
    - ``"interactive"`` — active only when constructed for a multi-turn
                          session (REPL, TUI, gateway). One-shot commands
                          have no "next turn" to inject recovery into, so
                          paying the snapshot cost there is wasted.
    - ``"never"``      — disabled entirely; loop is byte-identical to the
                          pre-Bug2 baseline (no commits, no interrupt
                          reclassification, no recovery injection).

    Default ``"interactive"`` matches mature competitors (Claude Code,
    Cursor) which transparently checkpoint long sessions while leaving
    one-shot batch invocations untouched.
    """

    policy: Literal["always", "interactive", "never"] = "interactive"
    """When the per-turn shadow-git snapshot is active. See class
    docstring for the interaction with the AgentLoop ``interactive`` flag."""

    shadow_dir: str = ".pico/shadow.git"
    """Shadow git-dir, relative to Workspace State for project-local foreground
    runs and to the Workspace for colocated legacy/service runs. The real
    Workspace is the work-tree; the user's own ``.git`` is never touched."""


class RuntimeConfig(_Base):
    """Runtime discipline — the 4th feature pillar.

    Houses the opt-in runtime safety nets. Bug2 ships ``checkpoint``;
    later phases add ``journal`` / ``verifier`` / ``done_gate`` /
    ``loop_detection`` (Bug3, us) and ``session`` (Bug1, dev) as sibling
    sub-configs. All default off so the all-off baseline equals 68a3be7.
    """

    checkpoint: CheckpointConfig = Field(default_factory=CheckpointConfig)


class TracingConfig(_Base):
    """Observability tracing (in-tree ``pico.tracing``).

    On by default; every ``pico`` command auto-installs non-invasive
    instrumentation before any AgentLoop is built. ``PICO_TRACING=0`` is an
    explicit env kill-switch that overrides this block. View captured traces
    with ``pico tracing`` (or ``/tracing`` in the TUI).
    """

    enabled: bool = True
    port: int = 4318
    preview_len: int = 500


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class PicoConfig(_Base):
    """Pico root config. Composes the base Config with feature extensions."""

    # Feature blocks
    context: ContextConfig = Field(default_factory=ContextConfig)
    token_wise: TokenWiseConfig = Field(default_factory=TokenWiseConfig)
    # SkillForge subsystem — its RRF routing policy nests at
    # ``skill_forge.router`` (config key ``skillForge.router``), no longer a
    # separate top-level ``skillRouter`` block.
    skill_forge: SkillForgeConfig = Field(default_factory=SkillForgeConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)

    # CFG-1: plugin system + memory backend.
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    # The full base config (agents, channels, providers, tools, routing).
    # Kept as a nested field so we can round-trip YAML with the base loader.
    base: BaseConfig = Field(default_factory=BaseConfig)


def load_pico_config(config_path: Path | None = None) -> PicoConfig:
    """Load both the base Config and the Pico extension blocks
    (``context`` / ``token_wise`` / ``skill_forge``) from
    the same JSON config file.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Extension blocks fall through to their dataclass defaults when the
    JSON has no entry for them; explicit ``null`` values are also
    treated as "use default" rather than rejected.
    """
    base = load_base_config(config_path)

    overrides: dict = {}
    actual_path = config_path or get_config_path()
    if actual_path.exists():
        try:
            with open(actual_path, encoding="utf-8") as f:
                data = json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            data = {}
        # Apply the same migrations the base loader uses before extracting
        # extension blocks.
        data = _migrate_config(data, pop_extension_keys=False)
        # Warn once when the user still has the ignored legacy
        # ``skill_forge.mass_library_db`` field.
        _warn_mass_library_db_deprecated(data)
        for key in EXTENSION_KEYS:
            if key in data and data[key] is not None:
                overrides[key] = data[key]

    return PicoConfig(base=base, **overrides)


def _warn_mass_library_db_deprecated(data: dict) -> None:
    """Single-shot deprecation warning for ``skill_forge.mass_library_db``.

    The legacy SQLite field is retained for config compatibility but
    ignored by Local Skill retrieval.
    """
    legacy = None
    for skill_forge_key in ("skill_forge", "skillForge"):
        block = data.get(skill_forge_key)
        if isinstance(block, dict):
            legacy = block.get("mass_library_db") or block.get("massLibraryDb")
            if legacy:
                break
    if not legacy:
        return
    warnings.warn(
        "skill_forge.mass_library_db is deprecated and ignored. Local skills "
        "are discovered from configured filesystem sources; remove this field.",
        DeprecationWarning,
        stacklevel=2,
    )
