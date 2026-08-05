# Pico evolution

Pico evolves by deepening one shared Agent Runtime instead of accumulating
parallel execution paths. This document records the current engineering rules;
commit-bound evidence remains authoritative for individual claims.

## Product direction

Pico owns the visible Agent experience: CLI, native TUI, Gateway, Cron,
Channels, Sessions, Context, Tools, Tracing, and lifecycle coordination.
Installed Plugins own optional capabilities behind public interfaces.
CodeCairn, for example, owns repository-scoped Memory and its storage lifecycle.

The Runtime is general-purpose. Pico does not present itself as a Coding Agent,
train model weights, or treat candidate generation as autonomous improvement.

## Delivery rules

1. **One Turn contract.** Every host enters through Spine and exits through the
   same delivery path.
2. **One owner per lifecycle.** Runtime, Plugin, Session, Memory, and host
   teardown responsibilities remain explicit.
3. **Vertical changes.** A feature change includes its public surface,
   configuration, implementation, tests, packaging, and documentation.
4. **Evidence keeps its class.** Deterministic, live, fixture, skipped,
   inconclusive, Provider failure, and infrastructure failure are not
   interchangeable.
5. **Candidates remain inactive.** Evolver output requires an explicit verdict,
   manual activation, and rollback evidence where applicable.
6. **Installed behavior matters.** Source checks do not replace wheel, fresh
   process, host-parity, or external integration verification.

## Current focus

- Keep CLI, TUI, Gateway, Cron, Channels, and Subagents aligned on the shared
  Runtime Assembly.
- Strengthen Session continuity, Context budgeting, Tool safety, and tracing.
- Keep Memory replaceable through the installed Plugin interface.
- Make release claims only from candidate-bound evidence.
- Improve Evolver evaluation without broadening activation authority.

See [Project status](project-status.md),
[Feature evidence](feature-evidence.md), and [Roadmap](roadmap.md) for current
implementation, evidence, and open work.
