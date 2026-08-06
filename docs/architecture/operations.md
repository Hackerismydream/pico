# Operations and extension surfaces

This document covers configuration, Providers, Routing, TokenWise, Channels,
Cron, Sandbox, Tracing, package boundaries, and operational failure behavior.

## Runtime prerequisites

| Component | Requirement |
| --- | --- |
| Python Runtime | Python 3.12 (`>=3.12,<3.13`) |
| Package/environment manager | `uv` for repository work |
| Native TUI | Node.js 22 or newer at runtime |
| base Agent | configured LLM Provider or custom compatible endpoint |
| Feishu | `channel-feishu` extra and valid app credentials |
| QQ | `channel-qq` extra and valid bot credentials |
| WeCom | `channel-wecom` extra and valid bot credentials |
| BoxLite Sandbox | `sandbox` extra and supported host |
| CodeCairn Memory | installed pinned distribution and `codecairn init` in the target Git repository |
| live Channels | external platform access and redacted evidence storage |

The wheel contains the built TUI JavaScript bundle and local tracing viewer. It
does not contain a Node executable.

## Configuration model

Pico reads one JSON config and builds:

- base `Config`: agents, Channels, Providers, Gateway, Web/Exec/MCP Tools,
  Routing, Cron, language, and Workspace;
- Pico extensions: Context, TokenWise, SkillForge, Plugins, Memory, Runtime,
  and Tracing.

Extension models reject unknown fields. Loader behavior is not uniformly
fail-closed:

- schema validation errors are visible;
- atomic update paths reject malformed JSON rather than overwriting it;
- ordinary base config loading may warn and start from defaults after malformed
  JSON.

Operators should run `pico doctor` after any recovery-to-default warning.
Documentation must not say every configuration error is fail-closed.

Configuration updates should use the existing loaders and atomic writers. They
must not rewrite unrelated sections or serialize secrets into diagnostics.

## Public operational surface

| Goal | Command |
| --- | --- |
| native TUI | `pico` |
| interactive terminal Agent | `pico run` |
| one-shot Turn | `pico run -m "..."` |
| guided setup | `pico onboard` |
| local diagnostics | `pico doctor` |
| Runtime readiness | `pico status` |
| Provider management | `pico provider ...` |
| Channel management | `pico channels ...` |
| Gateway | `pico gateway` |
| Session lifecycle | `pico sessions ...` |
| scheduled work | `pico cron ...` |
| Skill inspection | `pico skills ...` |
| Plugin inspection | `pico plugins ...` |
| tracing viewer | `pico tracing` |
| Evolver Beta | `pico evolve check\|run\|status\|finalize` |

Sandbox administration exists in advanced/hidden help. Sentinel and Deep
Research commands do not exist.

## Providers

`pico/providers/registry.py` is the catalog authority. The current Config has
entries for:

- custom OpenAI-compatible;
- Azure OpenAI;
- Anthropic;
- OpenAI;
- OpenRouter;
- DeepSeek;
- Groq;
- Zhipu;
- DashScope;
- vLLM;
- Gemini and Vertex AI;
- Moonshot;
- MiniMax;
- AiHubMix;
- Ollama;
- SiliconFlow;
- VolcEngine;
- OpenAI Codex OAuth;
- GitHub Copilot OAuth.

Catalog presence means Pico can construct the configured adapter path. It does
not mean every Provider/model combination has current live evidence.

### Abstraction and retries

`LLMProvider` normalizes:

- non-stream and stream response shapes;
- visible text and reasoning;
- Tool calls;
- token Usage;
- error classification.

General error behavior:

| Classification | Behavior |
| --- | --- |
| context overflow | let Agent Loop shrink context and retry within its bound |
| rate limit, server, or network | bounded retry, then configured fallback |
| billing or model unavailable | eligible for fallback |
| authentication, ordinary bad request, unknown terminal | fail the Turn |

`LazyProvider` may warm configuration in the background, but the first real
request remains the authority for credentials and endpoint readiness.

OAuth-backed Providers have dedicated login state. Other hosted Providers are
normally routed through LiteLLM. `CustomProvider` and per-model endpoints
support OpenAI-compatible services.

## Routing

Routing is optional and availability-first.

### EcoClaw-style routing

The selector uses task classification and benchmark profiles. If profiles,
embeddings, classification, or model selection fail, it retains the default
model. A successful Turn after fallback is not evidence that the Router made a
high-confidence decision.

### KNN routing

The KNN Router compares the current task to a prebuilt memory of per-model
reward and cost. It leaves the default model in place unless all configured
support thresholds are satisfied:

- enough memory entries;
- enough sufficiently similar neighbors;
- enough margin over the default;
- a routable endpoint.

`PerModelProvider` dispatches a selected model to its endpoint. Route
configuration is not model-weight training.

## TokenWise

TokenWise is a Strategy chain around Provider calls, not a separate Agent
Runtime.

Retained implementations:

- `StrategyRegistry`: ordered `before_llm_call` and `after_llm_call` hooks;
- `UsageTracker`: per-call token/cost snapshots and aggregate accounting;
- `CacheOptimizer`: Anthropic-compatible prompt cache breakpoint placement;
- `SystemAndTailCacheStrategy`: a reference cache placement variant;
- pricing and model-catalog helpers.

The shared Runtime Assembly does not currently install the configured TokenWise
chain. Experiments inject a StrategyRegistry explicitly; mechanism evidence
must not be reported as current host activation.

Before-hook errors fail fast because they may corrupt the Provider request.
After-hook errors are logged and swallowed so telemetry cannot fail the Turn.

Cost values are estimates based on the known model catalog, not invoices.
Historical `EXPERIMENT_REPORT*.md` results are dated measurements with pinned
models and Provider behavior, not current release benchmarks.

## Channels

The official registry contains exactly Feishu, QQ, and WeCom.

### Optional dependency isolation

Each adapter exposes a cheap `ChannelSpec`. The SDK is imported in the factory
only when enabled. The aggregate `channels` extra installs all three; individual
extras install one.

An adapter may fail configuration, dependency import, or startup without
preventing other adapters from starting. The Gateway reports enabled and
disabled states.

### Shared contract

Channels normalize:

- text and media input;
- sender/chat identity;
- direct versus group context;
- allowlist policy;
- outbound `Text` and `MediaOut`;
- start/stop lifecycle.

Empty `allow_from` is invalid. The current default `["*"]` is open access and
should be restricted in a real deployment.

### Current readiness

- Feishu: live-gated by the required real V-LF tracer bullet passed on
  2026-07-27; the claim remains bound to the report's commit and scenario.
- QQ: contract-verified Beta after PR #50; no live bot claim.
- WeCom: contract-verified Beta after PR #50; no live bot claim.

Gateway Channel output is final-message delivery, not edit-in-place streaming.
The outbound queue is in memory and not durable across process exit.

## Cron

Cron stores user-created jobs, computes fires in an IANA timezone, claims due
work, submits `Origin.CRON` through the Gateway's system pool, records terminal
state, and forwards output.

Supported operational behavior includes:

- cron expressions and interval jobs;
- timezone and DST handling;
- enable/disable and immediate run;
- persistent claims and restart recovery;
- one-shot completion;
- explicit forwarding targets.

Ephemeral origins such as CLI/TUI cannot deliver after their process exits.
The configured forward Channels determine where their scheduled result goes.

Cron is not Sentinel. No background component invents a task or decides to
nudge a user.

## Sandbox

Sandbox selection is explicit:

| `tools.sandbox.backend` | Behavior |
| --- | --- |
| `none` | `DirectExecutor`; command and compatible MCP subprocesses run on the host with a reduced environment |
| `auto` | currently requires a working BoxLite installation; no direct fallback |
| `boxlite` | requires BoxLite and creates a microVM on demand |

The default is `none`. Pico logs that host execution is active.

### Direct executor

Direct execution applies:

- reduced environment inheritance;
- optional Workspace restriction;
- dangerous-command heuristics;
- timeout and Tool-result fencing.

These are application controls, not an operating-system Sandbox.

### BoxLite executor

BoxLite provides:

- microVM process boundary;
- Workspace mounted at `/workspace`;
- explicit extra read-only or read/write volumes;
- optional network or domain policy;
- lazy VM creation;
- compatible MCP stdio execution in the VM;
- a debug server and direct administrative script.

Selecting `auto` or `boxlite` without the pinned optional dependency and a
working host probe raises `SandboxInitError`. It does not silently run the
command on the host.

### Security boundary

Neither backend makes arbitrary Agent execution safe by itself:

- direct mode is host execution;
- BoxLite mounts the configured Workspace read/write;
- Tool restrictions and untrusted-content fences mitigate common mistakes and
  prompt injection but are not a hostile-code proof;
- credentials passed to a subprocess remain in that subprocess's authority.

See [Sandbox usage](../sandbox/usage.md).

## MCP and Tools

MCP supports:

- stdio;
- SSE;
- streamable HTTP.

Registered names use `mcp_<server>_<tool>`. Calls have per-Tool timeouts and
return failed Tool results rather than untyped exceptions.

Progressive Tool disclosure activates only when the live Tool catalog exceeds
its threshold. It then exposes `tool_search` and `tool_call` meta-Tools plus a
small always-visible core.

Known connection limitation: an MCP server connection failure is isolated from
the Agent host, but current connection iteration may stop before attempting
later configured servers in that pass.

Untrusted Web, file, shell, MCP, Subagent, and Memory content is fenced before
being returned to the model. Network validation rejects private/reserved
targets and unsafe redirects in protected Tool paths.

## Tracing

`pico.tracing` is a local, non-interfering observability layer:

- `trace.span` and `trace.instrument` facade;
- ContextVar parent/child propagation;
- `audit.span.v1` records;
- out-of-line artifacts;
- JSONL logs and rotation;
- bundled local Node viewer launched by `pico tracing`.

Tracing defaults on and can be disabled with Config or `PICO_TRACING=0`.
Tracing failures are swallowed; application exceptions are re-raised unchanged.

Current limitations:

- no OpenTelemetry exporter or centralized collector;
- best-effort append/rotation rather than a multi-process ledger;
- V-TE0 correlates Turn tracing, usage, delivery, and terminal states as
  deterministic contract evidence; full release aggregation remains V-R0;
- artifact digests identify content but do not form signed attestations.

See [Tracing Standard API](../TRACING_STANDARD_API.md).

## Packaging and release boundary

`pyproject.toml` packages only the `pico` Python namespace. The custom build
hook includes the prebuilt TUI bundle when present.

V-P0:

1. creates an isolated source snapshot;
2. builds the TUI;
3. builds wheel and sdist;
4. validates the exact wheel manifest;
5. installs the base and every retained extra in separate environments;
6. probes installed CLI, TUI, Gateway, help, and doctor with empty
   `PYTHONPATH`;
7. rebuilds a wheel from the sdist;
8. compares direct and sdist-derived wheels except generated `RECORD`.

The verifier rejects:

- unexpected compatibility namespaces or entry points;
- removed Channel, Sentinel, Heartbeat, Deep Research, media generation, or
  Remote Skill Hub code;
- unexpected TUI bundles;
- checkout-only report assets;
- missing licenses or retained extras.

The source distribution remains a release artifact. The GitHub release
workflow is currently draft and PyPI publication is not enabled.

One known package gap is recorded in [Project status](../project-status.md):
the source-tree weather Skill is not included by the current wheel allowlist.

## Operator diagnostics

Use:

```bash
pico status
pico doctor
pico channels status
pico plugins
pico --check
```

Interpretation rules:

- `--help`, `--check`, or `/v1/models` reachability is not live inference
  proof;
- a loaded Plugin manifest is not a successfully started backend;
- an enabled Channel is not a successful inbound/outbound tracer bullet;
- a fallback model Turn is not proof of the preferred route;
- a tracing record is not automatically release evidence;
- a skipped live test is not a passing Gate.

## Verification map

| Surface | Canonical verification |
| --- | --- |
| Config and CLI | focused CLI/config tests and `pico doctor` |
| Providers and fallback | provider unit tests; V-LP for one real Provider |
| Routing | Router threshold and fallback tests |
| TokenWise | Strategy/cache/usage tests |
| Channel contract | adapter and Channel Interface tests; V-C0 |
| real Feishu | V-LF, passed 2026-07-27 |
| Cron | service, claim, timezone, and Gateway integration tests |
| Sandbox | unit tests; opt-in `real_vm` for BoxLite |
| Tracing | API/conformance tests; V-TE0 for correlated Turn evidence |
| Package boundary | V-P0 |
| release | V-R0 driver implemented; no complete pass recorded |
