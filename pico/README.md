# Pico Runtime package

`pico/` is Pico's Python namespace. It contains the Runtime used by the `pico`
command. The package is intentionally split by responsibility so CLI commands,
provider adapters, memory, routing, channels, and scheduled execution can evolve
without coupling everything through one agent loop.

The cross-module architecture, lifecycle, and current limitations are documented
in [`docs/architecture/README.md`](../docs/architecture/README.md). Canonical
domain terms live in [`CONTEXT.md`](../CONTEXT.md).

## Package ownership

| Package | Responsibility |
| --- | --- |
| `cli/` | Typer commands, onboarding, and host composition |
| `spine/` | Turn requests, per-conversation scheduling, cancellation, lifecycle events, and delivery queues |
| `agent/` | Agent Loop, Tools, MCP, Subagents, recovery, Checkpoints, and the Agent-side Turn Runner |
| `tui_rpc/` | Python JSON-RPC boundary and TUI-specific Turn/event wiring |
| `channels/` | Feishu, QQ, and WeCom contracts, intake, manager, and outbound adapter |
| `proactive_engine/schedulers/cron/` | retained user-scheduled Cron only; Sentinel and Heartbeat are removed |
| `session/` | atomic JSONL Sessions, fork, export, resolution, and deletion |
| `context_engine/` | one Context Assembler, six prompt segments, Curator, archive, and fail-safe |
| `memory_engine/` | Memory backend Protocol, Local Skills, and SkillForge routing |
| `plugin/` | manifest discovery, Registry, and installed Memory/Tool contributions |
| `providers/` | LLM abstraction, catalog, retries, fallback, and streaming |
| `routing/` | optional task-level model selection |
| `token_wise/` | Provider-call strategies, cache placement, usage, and estimated cost |
| `sandbox/` | direct host executor, optional BoxLite executor, and debug server |
| `tracing/` | local non-interfering spans, storage, artifacts, and viewer |
| `evolver/` | opt-in Evolution Runs, candidate evidence, Gates, activation artifacts, and rollback |
| `eval_engine/` | retained source not currently mounted by shared Runtime Assembly |
| `config/` | base and Pico extension schemas, loading, migration, and atomic updates |
| `security/` | untrusted-content fencing and protected network checks |
| `templates/` | Workspace templates materialized by Pico |

Runtime code should not import from `benchmarks/`, `demos/`, or `tests/`.
Evolver may lazily load a registered benchmark plugin from `benchmarks/` only
for an explicit Evolution Run; normal Runtime and installed package startup do
not.
