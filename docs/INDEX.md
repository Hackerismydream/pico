# Pico documentation index

This page is the canonical entry point for Pico documentation. It separates
current product and implementation contracts from execution plans, historical
evidence, research notes, and executable Markdown data.

Pico is currently an Alpha, pre-release-candidate Agent Harness. Package
metadata is `0.1.7`; see [Project status](project-status.md) for the current
claim boundary.

The separate Pico Harness v0.1 portfolio/engineering milestone is complete.
The Pico Harness v0.2 CodeCairn implementation and joint evidence campaign are
complete; this is an engineering/product milestone, not current package
semver. The paired measurement is valid, but the positive claim is ineligible
because every hard-negative query returned three irrelevant memories.

## Read this first

An Agent starting work in this repository should read these sources in order:

1. [AGENTS.md](../AGENTS.md) for hard repository workflow rules.
2. [README.md](../README.md) for the public product boundary.
3. [Context map](../CONTEXT-MAP.md) and
   [Runtime glossary](../CONTEXT.md) for canonical domain terms.
4. [Architecture](architecture/README.md) for package ownership and the
   end-to-end Runtime path.
5. [Project status](project-status.md) for what is implemented, what is only
   deterministically verified, and what remains unproven.
6. [Feature-to-evidence matrix](feature-evidence.md) for exact implementation
   entry points and claim classes.
7. [Roadmap](roadmap.md) for the committed delivery sequence and explicitly
   non-committed future options.
8. [Developer guide](dev.md) before changing or verifying code.

When one of these documents conflicts with code, a current test, or package
metadata, the implementation wins until the documentation is repaired. When a
local roadmap summary conflicts with an open GitHub issue, the issue body is
the execution contract.

## Source-of-truth hierarchy

| Question | Authoritative source |
| --- | --- |
| What Pico v1 is | [Issue #1](https://github.com/Hackerismydream/pico-harness/issues/1) and the root README |
| What a domain term means | [CONTEXT-MAP.md](../CONTEXT-MAP.md), [CONTEXT.md](../CONTEXT.md), or [ui-tui/CONTEXT.md](../ui-tui/CONTEXT.md) |
| What is implemented now | Code on `main`, package metadata, and current tests |
| What work is next | Open GitHub issues, summarized in [roadmap.md](roadmap.md) |
| What evidence supports a claim | Gate output tied to a commit or merged PR, summarized in [project-status.md](project-status.md) |
| How to build and verify | [dev.md](dev.md), the `Makefile`, and verifier scripts |
| How an Evolution Run works | [pico/evolver/README.md](../pico/evolver/README.md) and the current implementation mapping |

The repository does not treat a proposal, an unchecked issue checklist, a
fixture-backed pass, a skipped live test, or an infrastructure failure as
proof that the corresponding product behavior works.

## Architecture and contracts

| Document | Scope |
| --- | --- |
| [Architecture overview](architecture/README.md) | System boundary, package map, dependency direction, lifecycle ownership, and architectural constraints |
| [Runtime and Turn flow](architecture/runtime.md) | CLI, TUI, Gateway, Channel, Cron, and Subagent entry paths through Spine and Agent Loop |
| [State, Context, Memory, and Skills](architecture/state-and-intelligence.md) | Session persistence, Context segments, Curator, CodeCairn, Local Skills, Plugins, and state roots |
| [Operations and extension surfaces](architecture/operations.md) | Providers, Routing, TokenWise, Channels, Cron, Sandbox, Tracing, configuration, and packaging |
| [Evolver architecture](architecture/evolver.md) | Evolution Run lifecycle, benchmark inversion, candidate evidence, activation, rollback, and threat model |
| [Agent application evaluation](evaluation/README.md) | Implemented checkout-only PicoBench boundary, Runtime relationship, experiment state, and claim discipline |
| [PicoBench Ship-1 contract](evaluation/picobench-ship-1.md) | Runtime, Context, Memory/Skill, Tool/MCP, and paired-evaluation task protocol |
| [PicoBench semantic addendum](evaluation/picobench-semantic-addendum.md) | Historical production EverOS semantic retrieval, source fusion, cumulative budget, and separate claim gates |
| [CodeCairn Memory backend](specs/codecairn-memory-backend.md) | Current v0.2 cross-repository Interface, ownership, lifecycle, Source Journal, failure semantics, and acceptance Gates |
| [Channel evidence contract](specs/channel-evidence-gates.md) | V-C0, V-S0, adapter maturity, deterministic matrices, and live-evidence boundary |
| [Turn evidence correlation](specs/turn-evidence-correlation.md) | V-TE0 trace, usage, delivery, terminal-state, and verifier contract |
| [Release candidate Gate](specs/release-candidate-gate.md) | V-R0 layer ordering, commit binding, result classification, and fail-closed aggregation |
| [Runtime glossary](../CONTEXT.md) | Canonical Runtime terms; update in the same change when a new domain term is introduced |
| [TUI glossary](../ui-tui/CONTEXT.md) | Canonical React/Ink and TUI-RPC terms |
| [TUI README](../ui-tui/README.md) | Supported TUI surface and development workflow |
| [Tracing Standard API](TRACING_STANDARD_API.md) | Current write-side tracing facade and semantic conventions |
| [Memory and Plugin architecture](memory-plugin-architecture.md) | Current `MemoryBackend`, Plugin Registry, and installed CodeCairn contract |
| [Sandbox usage](sandbox/usage.md) | Actual host-execution default, BoxLite opt-in behavior, and security boundary |

Module-local documentation remains colocated with its implementation:

- [Python package map](../pico/README.md)
- [Evolver user and operator guide](../pico/evolver/README.md)
- [Evolver orchestrator design](../pico/evolver/orchestrator/DESIGN.md)
- [Built-in skill data](../pico/memory_engine/skills/README.md)

## Current status, evolution, and plans

| Document | Scope |
| --- | --- |
| [Project status](project-status.md) | Current maturity, feature-to-evidence matrix, open problems, and evidence freshness |
| [Feature-to-evidence matrix](feature-evidence.md) | Capability entry points, strongest Gate, evidence class, and honest current claim |
| [Learning path](learning-path.md) | Runtime-first route through hosts, Spine, intelligence, operations, Evolver, and release evidence |
| [Evolution principles](evolution.md) | Current product direction, delivery rules, and engineering focus |
| [Roadmap and future](roadmap.md) | Remaining Issue #24 evidence, release order, and post-v1 candidates |
| [Plan directory](plan/README.md) | How GitHub issues, local plan summaries, acceptance Gates, and future ideas relate |
| [PicoBench Ship-1 analysis](plan/analysis/picobench-ship-1.md) | Historical module alternatives, integration enumeration, dependency graph, and campaign boundary |
| [CodeCairn Memory replacement analysis](plan/analysis/codecairn-memory-replacement.md) | Replacement analysis, EverOS deletion inventory, cross-repository sequence, rollout, and evidence boundary |
| [Pico CodeCairn implementation Goal](plan/pico-codecairn-implementation-goal.md) | Delivery record for consuming the installed Adapter and removing active EverOS coupling |
| [Pico-CodeCairn joint evidence Goal](plan/pico-codecairn-joint-evidence-goal.md) | Completed execution record for installed continuity, isolation, paired evaluation, and claim reconciliation |
| [Delivery tasks](plan/tasks/README.md) | Completed PicoBench and CodeCairn delivery slices |

GitHub remains the live task tracker. The local roadmap explains the whole
sequence to readers; it does not duplicate issue acceptance checklists.

## Development and verification

| Document | Scope |
| --- | --- |
| [Developer guide](dev.md) | Setup and V-D0, V-T0, V-P0, V-LP, V-C0/V-S0, V-LF, V-TE0, V-E0, and V-R0 workflows |
| [Contributing](../CONTRIBUTING.md) | Contribution workflow |
| [Releasing](../RELEASING.md) | Release procedure and release evidence |
| [Tests README](../tests/README.md) | Test layout, marker boundaries, and which commands prove which layer |
| [Scripts README](../scripts/README.md) | Checkout-only linters, verifiers, live probes, evaluators, and Sandbox utilities |
| [Historical EverOS E2E plan](everos-memory-e2e-test-plan.md) | Retained pre-CodeCairn extraction, recall, and cross-process continuity contract; not a current Gate |
| [BoxLite CLI](sandbox/boxlite_cli.md) | Direct VM administration outside the running Agent |
| [Sandbox debug commands](sandbox/debug_commands.md) | Runtime-owned VM debugging through the Sandbox debug socket |
| [TUI autotest](../tests/tui/autotest/README.md) | Black-box terminal harness and opt-in subprocess tests |

## Evolver methodology and benchmark contracts

| Document | Lifecycle | Scope |
| --- | --- | --- |
| [Evolver README](../pico/evolver/README.md) | Current | Public CLI, run specification, durable artifacts, current limitations, and security notes |
| [Benchmark plugin contract](specs/evolve-bench-contract.md) | Current | `BenchBundle` integration contract |
| [SOP-to-code mapping](specs/self-evolution-loop-implementation.md) | Current | Clause-by-clause mapping from methodology to Pico implementation |
| [Self-evolution SOP](specs/self-evolution-loop-sop.md) | Methodology plus dated history | Research method. Its historical rollout-status appendix is not the current implementation status |
| [AppWorld example](examples/evolve_appworld.yaml) | Executable example | Annotated Evolution Run specification |
| [Subject Runtime example](examples/subject_runtime.json) | Executable example | Benchmarked Agent Provider configuration |

AppWorld remains the checkout example. The small-real release harness creates a
disposable subject repository that owns its benchmark plugin. References to
EvoAgentBench or other benchmark lines remain future examples unless
corresponding code exists.

## Teaching snapshot

[中文架构与面试教程](tutorial-zh/README.md) is a detailed teaching snapshot.
Its implementation narrative is deliberately pinned to PR #47 and its first
evidence review to PR #53 so readers can reproduce the chapter claims. The
tutorial ledger also records the current PR #56 checkpoint and later
corrections. It is not the current project authority; use this index,
[Project status](project-status.md), [Feature evidence](feature-evidence.md),
and current code for operational decisions.

## Benchmarks and executable Markdown

[benchmarks/README.md](../benchmarks/README.md) owns benchmark setup and the
independent-evaluation boundary. Benchmark task cards under
`benchmarks/pinchbench/tasks/` are executable fixtures, not product
documentation. Some deliberately probe capabilities Pico no longer ships,
such as image generation or remote Skill discovery. Their presence does not
restore or advertise those capabilities.

Workspace templates under `pico/templates/`, `SKILL.md` files, and plugin
manifests are executable data. They should be reviewed against their loaders,
not interpreted as free-standing product claims.

## Historical evidence and research

TokenWise experiment reports are dated measurements. Model availability,
prices, Provider routing, and measured results are snapshots rather than
current release claims. Current claims require a Gate bound to the candidate
commit.

## Legal, security, and repository policy

- [Security policy](../SECURITY.md)
- [Code of Conduct](../CODE_OF_CONDUCT.md)
- [Apache-2.0 license](../LICENSE)
- [Notices and upstream provenance](../NOTICES.md)
- [Third-party license bundle](../LICENSES/README.md)
- [AI collaboration rules](../AGENTS.md)

## Documentation maintenance rules

1. Put cross-module architecture and lifecycle decisions under `docs/`.
2. Keep module-local commands and contracts beside the module, then link them
   from this index.
3. Mark every document as current, planned, historical, or executable data.
4. Never copy volatile test counts into an architecture contract. Put counts in
   commit-bound evidence or `project-status.md` with their source and age.
5. Update terminology, implementation docs, tests, packaging, and examples in
   the same change when a public surface changes.
6. Do not turn a fixture, fallback, skipped live test, or old PR result into a
   current claim.
7. Keep large logs and report assets outside Git. Commit schemas, verifiers,
   rerun commands, and concise indexes only.
