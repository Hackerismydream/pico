# Context Map

> **Status: Pico v1 implementation glossary.** Product and Python module terms
> use the canonical Pico vocabulary defined here.

## Contexts

- [Pico Runtime](./CONTEXT.md) — the Python Agent Runtime: Channels, Spine,
  Agent Loop, Context, Memory, Providers, and state ownership
- [TUI](./ui-tui/CONTEXT.md) — the terminal frontend (`ui-tui/`, React/Ink); talks to the Runtime only via TUI-RPC

## Architecture and project state

- [Documentation index](./docs/INDEX.md) — reading order and source-of-truth hierarchy
- [Architecture](./docs/architecture/README.md) — package ownership, dependency direction, lifecycle, and cross-module flows
- [Agent application evaluation](./docs/evaluation/README.md) — PicoBench
  boundary, experiment terms, and claim discipline
- [Myna Memory backend](./docs/specs/myna-memory-backend.md) - current public
  Interface, installed Adapter ownership, and durable source capture boundary
- [Project status](./docs/project-status.md) — implementation and evidence boundary
- [Roadmap](./docs/roadmap.md) — committed issues and non-committed future candidates

## Relationships

- **TUI ↔ Runtime**: communicate exclusively over the TUI-RPC protocol
  (`pico/tui_rpc/`); the TUI never imports Runtime internals.
- **Hosts ↔ Runtime**: CLI, TUI, Gateway, Cron, and Channels submit Turns through
  Spine and share the Turn Runner contract.
- **Pico to Myna integration**: Pico keeps the `MemoryBackend` Interface and
  Myna owns the installed Adapter, Pico Source Journal, repository identity,
  import, and recall Implementation. Installed contract checks do not establish
  task-effect, performance, or production-success claims.
- **Glossary ↔ architecture docs**: this map and the two `CONTEXT.md` files own
  canonical terminology. Architecture documents explain relationships and
  lifecycle but do not coin competing synonyms.
