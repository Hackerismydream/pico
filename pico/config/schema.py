"""Configuration schema using Pydantic."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

from pico.product import DEFAULT_WORKSPACE_SPEC, get_default_workspace
from pico.sandbox.config import SandboxConfig


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FeishuConfig(Base):
    """Feishu/Lark channel configuration using WebSocket long connection."""

    enabled: bool = False
    app_id: str = Field(default="", json_schema_extra={"required": True})  # App ID from Feishu Open Platform
    app_secret: str = Field(default="", json_schema_extra={"required": True})  # App Secret from Feishu Open Platform
    encrypt_key: str = ""  # Encrypt Key for event subscription
    verification_token: str = ""  # Verification Token for event subscription
    allow_from: list[str] = Field(default_factory=lambda: ["*"])  # Allowed user open_ids; ['*'] = anyone
    react_emoji: str = "THUMBSUP"  # Emoji type for message reactions (e.g. THUMBSUP, OK, DONE, SMILE)
    group_policy: Literal["open", "mention"] = "mention"  # "mention" responds when @mentioned, "open" responds to all


class QQConfig(Base):
    """QQ channel configuration using botpy SDK."""

    enabled: bool = False
    app_id: str = Field(default="", json_schema_extra={"required": True})  # bot AppID from q.qq.com
    secret: str = Field(default="", json_schema_extra={"required": True})  # bot AppSecret from q.qq.com
    allow_from: list[str] = Field(default_factory=lambda: ["*"])  # Allowed user openids; ['*'] = public access


class WecomConfig(Base):
    """WeCom (Enterprise WeChat) AI Bot channel configuration."""

    enabled: bool = False
    bot_id: str = Field(default="", json_schema_extra={"required": True})  # Bot ID from WeCom AI Bot platform
    secret: str = Field(default="", json_schema_extra={"required": True})  # Bot Secret from WeCom AI Bot platform
    allow_from: list[str] = Field(default_factory=lambda: ["*"])  # Allowed user IDs; ['*'] = anyone
    welcome_message: str = ""  # Welcome message for enter_chat event


class ChannelsConfig(Base):
    """Configuration for chat channels."""

    send_progress: bool = True  # stream agent's text progress to the channel
    send_tool_hints: bool = False  # stream tool-call hints (e.g. read_file("…"))
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    qq: QQConfig = Field(default_factory=QQConfig)
    wecom: WecomConfig = Field(default_factory=WecomConfig)


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = DEFAULT_WORKSPACE_SPEC
    model: str = "anthropic/claude-opus-4-5"
    provider: str = "auto"  # Provider name (e.g. "anthropic", "openrouter") or "auto" for auto-detection
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    max_tool_iterations: int = 40
    # Cap on subagent VMs running at once (excess spawns queue). ge=1: a
    # 0/negative cap would deadlock every subagent (Semaphore(0)).
    max_concurrent_subagents: int = Field(default=4, ge=1)
    # Spawn rate limit per session, per rolling hour — the concurrency gate
    # alone can't stop a prompt-injected agent from spawning indefinitely (each
    # finishes, freeing a slot for the next; the cross-turn re-injection loop
    # needs no user input). A rolling window bounds a runaway to N/hour yet
    # auto-recovers, so it never permanently locks out heavy legitimate use.
    # Counted per session so one busy session can't throttle others.
    max_subagent_spawns_per_hour: int = Field(default=30, ge=1)
    # Empty-response recovery: recover turns the model ends with no visible text
    # (post-tool empty / thinking-only) instead of surfacing a dud "no response
    # to give". Budgets are per-turn.
    empty_recovery_enabled: bool = True
    post_tool_empty_max_nudges: int = 1
    thinking_prefill_max_retries: int = 2
    empty_content_max_retries: int = 3
    # Deprecated compatibility field: accepted from old configs but ignored at runtime.
    memory_window: int | None = Field(default=None, exclude=True)
    reasoning_effort: str | None = None  # low / medium / high — enables LLM thinking mode
    enable_personalization: bool = False  # 4-step PAHF-inspired personalization flow (classify → ask → execute → learn)

    @property
    def should_warn_deprecated_memory_window(self) -> bool:
        """Return True when old memoryWindow is present without contextWindowTokens."""
        return self.memory_window is not None and "context_window_tokens" not in self.model_fields_set


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class CronConfig(Base):
    """Cron scheduler configuration.

    Only consulted at cron job TRIGGER time, never at creation. Ephemeral
    channels (cli / tui — anything not in ChannelManager.enabled_channels)
    cannot deliver to themselves after the host process exits, so the
    forward_channels list resolves which real channels receive the reminder.
    """

    forward_channels: list[str] = Field(default_factory=lambda: ["*"])
    """Channels to deliver ephemeral-origin reminders to. ``["*"]`` broadcasts
    to every enabled channel. Specific names (``["feishu", "qq"]``)
    restrict to those. Non-ephemeral Channels ignore this list; they always
    pass through to the per-job Channel."""

    default_timezone: str = "Asia/Shanghai"
    """Default IANA timezone for cron expressions without explicit ``--tz``."""


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)
    models: list[str] = Field(default_factory=list)  # User-curated model names for the picker


class GeminiProviderConfig(ProviderConfig):
    """Gemini provider configuration with Vertex AI and multi-key support.

    Example YAML:
        gemini:
          vertex: true
          api_key_list:
            - "key1"
            - "key2"
    """

    vertex: bool = False  # When true, sets GOOGLE_GENAI_USE_VERTEXAI=True for Vertex AI
    api_key_list: list[str] = Field(default_factory=list)  # Multiple API keys for rotation

    def next_api_key(self) -> str:
        """Return the next API key using round-robin rotation.

        Falls back to single api_key if api_key_list is empty.
        """
        import itertools

        if not hasattr(self, "_key_cycle"):
            keys = self.api_key_list or ([self.api_key] if self.api_key else [])
            object.__setattr__(self, "_key_cycle", itertools.cycle(keys) if keys else None)
        cycle = getattr(self, "_key_cycle", None)
        if cycle is None:
            return self.api_key or ""
        return next(cycle)

    @property
    def effective_api_key(self) -> str:
        """Get the current effective API key (first from list, or single key)."""
        if self.api_key_list:
            return self.api_key_list[0]
        return self.api_key

    @property
    def all_keys(self) -> list[str]:
        """Return all configured API keys."""
        if self.api_key_list:
            return list(self.api_key_list)
        return [self.api_key] if self.api_key else []


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # Any OpenAI-compatible endpoint
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)  # Azure OpenAI (model = deployment name)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)  # Alibaba Cloud Tongyi Qianwen
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: GeminiProviderConfig = Field(default_factory=GeminiProviderConfig)  # Google Gemini / Vertex AI
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API gateway
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)  # Ollama local models
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # SiliconFlow
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenAI Codex (OAuth)
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig)  # Github Copilot (OAuth)


class ModelEndpoint(Base):
    """A routable model and the OpenAI-compatible endpoint that serves it."""

    model: str = ""
    api_base: str = ""
    api_key: str = "EMPTY"


class RoutingConfig(Base):
    """Model routing configuration.

    ``backend`` picks the router: ``ecoclaw`` (PinchBench benchmark scores, the
    original) or ``knn`` (task-level KNN over per-model rewards). Fields under
    "knn backend" are read only when ``backend == 'knn'``.
    """

    enabled: bool = False
    backend: str = "ecoclaw"  # ecoclaw | knn
    profile: str = "balanced"  # best / balanced / eco
    # OpenRouter API key for embeddings (ecoclaw backend; defaults to providers.openrouter.api_key)
    api_key: str = ""
    # knn backend: routable models paired with their endpoints
    models: list[ModelEndpoint] = Field(default_factory=list)
    # knn backend: prebuilt KNN memory (embeddings + per-model rewards/costs)
    memory_path: str = ""
    k: int = 30  # retrieval breadth: how many nearest neighbours to pull
    lambda_cost: float = 0.0  # score = reward - lambda_cost * cost
    embedding_endpoint: str = ""  # embedding service for the incoming task
    # knn backend safety gates: leave the default model only with enough evidence.
    # The pick is scored over the "similar" neighbours (cosine >= min_similarity).
    min_similarity: float = 0.6  # a neighbour counts as similar at cosine >= this
    min_similar_neighbors: int = 4  # need >= this many similar neighbours to route
    min_memory_size: int = 10  # need >= this many memory entries to route at all
    min_margin: float = 0.0  # only switch if the pick beats the default score by >= this


class GatewayLogConfig(Base):
    """Gateway logging configuration.

    ``rotation`` / ``retention`` accept loguru's vocabulary: rotation by size
    (``"10 MB"``), wall-clock (``"00:00"`` for daily), or interval
    (``"1 week"``); retention as a file count (``7``) or a duration
    (``"14 days"``).

    ``level`` filters the persisted ``gateway.log`` file; ``console_level``
    filters the live stderr mirror the foreground gateway keeps printing.
    """

    rotation: str = "10 MB"
    retention: int | str = 7
    level: str = "INFO"
    console_level: str = "INFO"


class GatewayConfig(Base):
    """Gateway/server configuration."""

    host: str = "0.0.0.0"
    port: int = 18790
    user_pool: int = 4
    system_pool: int = 2
    send_max_retries: int = 3
    log: GatewayLogConfig = Field(default_factory=GatewayLogConfig)


class WebSearchConfig(Base):
    """Web search tool configuration."""

    api_key: str = ""  # Serper API key
    max_results: int = 5


class WebToolsConfig(Base):
    """Web tools configuration."""

    proxy: str | None = None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    jina_api_key: str = ""  # Jina Reader API key
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell exec tool configuration."""

    timeout: int = 60
    path_append: str = ""


class MCPServerConfig(Base):
    """MCP server connection configuration (stdio or HTTP)."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None  # auto-detected if omitted
    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Stdio: extra env vars
    url: str = ""  # HTTP/SSE: endpoint URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP/SSE: custom headers
    tool_timeout: int = 30  # seconds before a tool call is cancelled


class ToolSearchConfig(Base):
    """Progressive tool disclosure.

    When the live tool catalog (built-ins + plugins + MCP) grows past
    ``compaction_threshold``, most tool schemas are withheld from each request and reached
    on demand through the ``tool_search`` / ``tool_call`` meta-tools, so context
    cost stops scaling with tool count and the per-turn tool list (and thus the
    prompt cache) stays stable. At or below the threshold every tool is exposed
    directly (unchanged behavior) and the meta-tools are omitted.
    """

    enabled: bool = False
    compaction_threshold: int = 50
    """Tool-catalog size that triggers compaction: at or below this many tools
    everything is exposed directly; above it, schemas are withheld."""
    search_result_limit: int = 10
    """Default number of hits ``tool_search`` returns per query."""
    always_visible: list[str] = Field(default_factory=list)
    """Extra tool names kept exposed every turn, on top of the core set."""


class ToolsConfig(Base):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig)
    disabled_tools: list[str] = Field(default_factory=list)
    """Tool names to unregister after default-tool registration and MCP connect.
    Used by eval harnesses (e.g. BrowseComp-Plus) that need to constrain the
    agent to a specific tool subset. Names match those in ``ToolRegistry``
    (e.g. ``read_file``, ``web_search``, or ``mcp_bcp-search_search``)."""


class Config(BaseSettings):
    """Root configuration for pico."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    cron: CronConfig = Field(default_factory=CronConfig)
    # UI language chosen during onboarding. Drives the wizard/CLI copy and the
    # agent's reply language (injected into the system prompt). "en" | "zh".
    language: Literal["en", "zh"] = "en"

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        workspace = self.agents.defaults.workspace
        return get_default_workspace() if workspace == DEFAULT_WORKSPACE_SPEC else Path(workspace).expanduser()

    def _match_provider(self, model: str | None = None) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        from pico.providers.registry import PROVIDERS

        forced = self.agents.defaults.provider
        if forced != "auto":
            p = getattr(self.providers, forced, None)
            return (p, forced) if p else (None, None)

        model_lower = (model or self.agents.defaults.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Explicit provider prefix wins — prevents `github-copilot/...codex` matching openai_codex.
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # Fallback: configured local providers can route models without
        # provider-specific keywords (for example plain "llama3.2" on Ollama).
        for spec in PROVIDERS:
            if not spec.is_local:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_base:
                return p, spec.name

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        p, _ = self._match_provider(model)
        return p

    def get_provider_name(self, model: str | None = None) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL for the given model. Applies default URLs for gateway/local providers."""
        from pico.providers.registry import find_by_name

        p, name = self._match_provider(model)
        if p and p.api_base:
            return p.api_base
        # Only gateways get a default api_base here. Standard providers
        # (like Moonshot) set their base URL via env vars in _setup_env
        # to avoid polluting the global litellm.api_base.
        if name:
            spec = find_by_name(name)
            if spec and (spec.is_gateway or spec.is_local) and spec.default_api_base:
                return spec.default_api_base
        return None

    @property
    def skill_forge(self):
        """Returns the default SkillForgeConfig. Extension blocks are
        loaded via ``load_pico_config``, not through the base
        Config. This property exists for backward compat with code that
        accesses ``config.skill_forge`` on a plain ``Config`` instance.
        """
        from pico.config.pico import SkillForgeConfig

        return SkillForgeConfig()

    model_config = ConfigDict(
        env_prefix="PICO_",
        env_nested_delimiter="__",
        extra="forbid",
    )
