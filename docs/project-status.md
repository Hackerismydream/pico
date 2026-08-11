# Pico project status

> Current implementation checkpoint: PicoBench Ship-1 and its held-out semantic
> v2 addendum, the Issue #21 V-LF closure recorded on 2026-07-27, and the
> current Myna public-seam integration, plus historical Issue #65 and Issue #70
> CodeCairn evidence. Issue #79 task-effect v2 calibration is complete,
> measurement-invalid, and blocked before its formal matrix. Campaign evidence
> remains bound to the source commits named below.
> Package metadata: `pico-harness 0.1.7`, Development Status Alpha.
> Release status: pre-RC; no Pico release tag exists.

This is the current-reality checkpoint for contributors and Agents. It
separates implementation, deterministic or contract evidence, live evidence,
historical evidence, and work that has not been demonstrated. Current Gate
output and commit-bound reports remain the final authority.

## Executive summary

Pico is a substantial Alpha Agent Harness, not a finished v1 Beta. It keeps one
coherent Runtime path while deliberately limiting unrelated product breadth:

- CLI, native TUI, Gateway, Channels, Cron, and Subagents submit Turns through
  Spine and the shared Agent Loop.
- Sessions, token-budgeted Context, repository-scoped Myna Memory, Local
  Skills, Plugins, Providers, Tools, Tracing, usage accounting, and delivery
  remain available across those hosts.
- Feishu, QQ, and WeCom share a deterministic Channel contract. Feishu is
  live-gated by a required V-LF run against the real Pico bot; QQ and WeCom
  remain contract-verified Beta adapters.
- V-TE0 now correlates Turn tracing, usage, terminal state, and Channel
  delivery as deterministic contract evidence.
- PicoBench Ship-1 completed 216 real-Provider Trials, 260 deterministic
  Retrieval Cases, and the R0/R1 Runtime tracks. The final-history task
  campaign is ship-complete but measurement-invalid because one Context Pair
  exhausted its symmetric retry without complete usage evidence. Tool
  disclosure also regressed task success, so no main-campaign positive metric
  is currently eligible.
- PicoBench task-effect v2 completed its installed calibration at clean Pico
  commit `d6ef624`: 12/12 task Trials terminated as Provider failures, 10/10
  retrieval cases were measurable, and 0/6 task Pairs were valid. The
  measurement and every Claim Gate are ineligible, so the 96-Trial formal
  matrix did not run. Issue #79 charged 1.29966592 CNY and left no open
  reservation.
- The current immutable Runtime artifact is bound to clean source commit
  `e6c790e`: 2,000 deterministic Scheduler requests produced zero lost
  requests, zero unexpected duplicate executions, and zero unresolved
  handles; R1 submitted 100 deterministic requests across success and failure
  scenarios, of which 92 produced readable Session and Delivery outcomes.
- The historical held-out semantic v2 addendum completed 260 records: 200
  exercised the former production EverOS retrieval path and 60 are Local-only
  BM25 controls. Those results remain bound to their source commit and are not
  current Myna evidence.
- Pico selects the separately installed Myna Plugin in fresh config, preserves
  Local Skills and the generic Memory Plugin contract, and keeps `null` as the
  explicit Memory-off setting. Pico carries no Myna source or local-path
  dependency. The installed composition Gate is technical contract evidence;
  no Myna task-effect, performance, or production-success claim exists.
- V-R0 exists as a fail-closed release driver, but no complete V-R0 result has
  passed.
- Evolver has a public Beta workflow, deterministic V-E0 coverage, and a
  tracked small-real subject harness. A real model has not yet completed that
  small-real run.

The remaining v1 release boundary includes a real small-real Evolution Run
verdict, formal availability of the compatible Myna artifact, and one clean,
commit-bound full V-R0 run followed by versioning and release.

## Pico Harness v0.1 portfolio milestone

**Pico Harness v0.1 portfolio/engineering milestone: complete.**

This local milestone names the coherent body of work that can be presented and
reviewed as an Agent application Runtime:

- one Turn Runtime across CLI, TUI, Gateway, Channels, Cron, and Subagents;
- Session, Context, Memory/Skill, Tool/MCP, tracing, and terminal-state
  semantics on that Runtime path;
- PicoBench Ship-1's frozen task, Runtime, retrieval, verifier, and report
  machinery;
- honest retention of the final-history measurement failure and Tool
  disclosure regression rather than a fabricated positive uplift.

The milestone does **not** mean any of the following:

- package version `0.1.7` is a new Pico release;
- formal Pico v1 or Issue #24 is complete;
- full V-R0 has passed;
- crash recovery or external-side-effect exactly-once behavior exists;
- PicoBench's main task campaign produced an eligible positive result.

The historical Pico-side Harness v0.2 milestone replaced active EverOS product
coupling with CodeCairn while preserving Local Skills. That former integration
has now been replaced by the Myna public seam. The historical campaign remains
bound to its original artifacts and is not evidence about Myna.

## Product boundary

### Retained

- Agent Loop, recovery, Synthesis, Tools, MCP, Web, Subagents, and optional
  workspace Checkpoints.
- CLI one-shot and interactive use, native TUI, background Gateway, Channels,
  Cron, and TUI-RPC.
- Session create, resume, fork, export, undo, delete, and atomic persistence.
- One Context Engine with Curator fast, slow, and deterministic fail-safe paths.
- Installed Myna Memory, Local Skills, SkillForge, and
  Plugin-contributed Memory backends and Tools.
- Feishu, QQ, and WeCom adapters with isolated optional SDK extras.
- Providers, custom OpenAI-compatible endpoints, Routing, TokenWise, Tracing,
  Sandbox configuration, and security controls.
- Opt-in Evolver Beta with human review, activation artifacts, and rollback.

### Removed

- WhatsApp and its Bridge, Telegram, Slack, Discord, Matrix, Mochat, DingTalk,
  Email, Weixin, and other non-target Channel adapters.
- Sentinel, Nudge, Task Discovery, proactive feedback, Heartbeat, and wake
  infrastructure.
- Media generation. Media input, attachment parsing, TUI and Channel
  attachments, and `MediaOut` delivery remain.
- Remote Skill Hub and marketplace discovery or installation. Local Skills
  remain.
- Bundled EverOS Memory, its direct dependency and configuration mutation,
  remembered-Skill source, feedback routing, and `understand_media`. Historical
  evidence and operator data remain untouched.
- Deep Research, MiroThinker, and their dedicated transport wiring. Ordinary
  Web Tools and MCP remain.
- Unsupported public commands, TUI compatibility fallbacks, and dynamic
  command discovery.

### Still out of scope for v1

- Automatic Runtime-candidate activation or model-weight training.
- Web, desktop, or mobile applications.
- Large distributed Evolution Runs.
- Enterprise tenants, billing, hosted administration, or a fixed source-line
  target.

## Feature-to-evidence checkpoint

“Implemented” means code exists. It does not imply current live evidence.
Counts and live claims below remain bound to the named clean source commit.

| Capability | Strongest recorded evidence | Current claim |
| --- | --- | --- |
| Deterministic Runtime benchmark | immutable Runtime evidence `1c9fc1c4882ff09e3cf44140d84206bfb5ce923344cf7e482615a36e4f0f6006` at clean source commit `e6c790e`: R0 recorded 2,000 accepted requests; R1 recorded 100 Scheduler submissions and 92 readable Session/Delivery outcomes | Claim eligible only as deterministic Scheduler and full-path composition evidence; not live throughput or a production SLO |
| CLI, TUI, and Gateway Runtime parity | PR #54 consumed a fresh V-P0 wheel: deterministic host Gate 1 passed; live DeepSeek V-LP 1 passed | Implemented; live Provider evidence is current only for PR #54 |
| Spine scheduling and Turn lifecycle | PR #51 V-TE0; PR #56 retained suite | Implemented and deterministically verified |
| Session and Context continuity | retained deterministic tests | Implemented; long-term backend state remains a separate durability domain |
| Myna Memory integration | installed Pico plus Myna composition verifier with pinned wheels | Public Plugin identity, compatibility, lifecycle, store/recall, fresh-process provenance, abstention, and fail-closed paths are contract-verified; no task-effect, performance, or production-success claim exists |
| Historical CodeCairn Memory integration | Issue #65 implementation plus Issue #70 experiment `1c5496edfaa08212635f6218f9aaa55c3e942fcd1e79203a11a6b8c4d9b94623` | Historical evidence bound to the recorded Pico and CodeCairn artifacts; not evidence about Myna |
| Historical EverOS continuity | PR #47 V-O0: 134 deterministic checks plus one required live EverOS check | Historical evidence for PR #47 only; not a current backend claim |
| Local Skills | retained deterministic tests with Myna selected and Memory off | Implemented independently of Memory; there is no remote marketplace |
| Persistent Cron through Spine | retained Cron tests; V-C0 delivery-resolution contract; required V-LF | Implemented; V-LF records exactly-once real Feishu delivery after Gateway restart |
| Feishu Channel | PR #50 V-C0/V-S0 contract; required V-LF passed 2026-07-27 | Live-gated for the exact commit and scenario recorded by the V-LF report |
| QQ and WeCom Channels | PR #50: V-C0 387 tests and V-S0 35 selections | Contract-verified Beta; no live bot claim |
| Tracing, usage, Turn terminal state, and delivery correlation | PR #51 V-TE0 passed | Deterministic contract evidence, not live evidence |
| PicoBench Agent task evaluation | experiment `abffb7d2fe6a76f1102741cacd3cff1ed02697be0fb37fe2fa7a910dbeb11b4d` at source commit `e6c790e`: 216/216 terminal Trials, 260/260 deterministic Retrieval Cases, and stable raw-artifact report rebuild | Ship complete but measurement invalid; one Context Pair lacks complete usage evidence, Tool disclosure regressed task pass count, and no main-campaign metric is eligible |
| Historical CodeCairn task-effect v2 | calibration experiment `6fbc169ee80ff29e7b8822e6a26992856706a69eab71853ba3e08338410ed11f` at Pico `d6ef624` and CodeCairn `555248e` | Historical campaign and Provider-boundary evidence only. Every Claim Gate was ineligible; no CodeCairn or Myna task-effect claim exists |
| Historical semantic Memory and Skill retrieval | semantic v2 experiment `98bb1e3cca2d1ee45dbebebef7f44db87fbea8ea23d1ea177843df6ba3ca2a1b` at source commit `e6c790e`: 260/260 records, including 200 former production EverOS retrieval records and 60 Local-only BM25 controls, with stable raw-artifact report rebuild | Eligible only for the recorded historical implementation; not current Myna evidence |
| Package outside checkout | PR #50 V-P0 passed; PR #54 built and consumed a fresh V-P0 wheel | Implemented; no V-P0 run is recorded for PR #56 |
| Sandbox | retained deterministic tests; opt-in `real_vm` tests | Direct host execution is default; BoxLite is opt-in and fail-closed when selected but unavailable |
| Evolver lifecycle, evidence, activation, and rollback | PR #56 V-E0: 319 passed | Implemented as opt-in Beta; fixture evidence is not a benchmark result |
| Small-real Evolver harness | PR #56 subject template, immutable grader, setup and lifecycle tests | Harness implemented; no real model run or outcome is recorded |
| Release candidate aggregation | PR #52 V-R0 driver and verifier tests | Driver implemented; no complete V-R0 pass or Pico release exists |

See [feature-evidence.md](feature-evidence.md) for the implementation entry
points and exact evidence classes behind each row.

## Candidate-label support

The Candidate Manifest recognizes six labels so evidence has a stable
vocabulary. This is not six mutation engines.

| Label | Schema | Can pass current G5? | Current boundary |
| --- | --- | --- | --- |
| `runtime` | Yes | Yes | Supported only for an exact benchmark-owned mutable surface, including the AppWorld example and tracked small-real subject |
| `skill` | Yes | No | Missing label-specific deterministic fixture and evaluator |
| `prompt` | Yes | No | Missing label-specific deterministic fixture and evaluator |
| `policy` | Yes | No | Missing label-specific deterministic fixture and evaluator |
| `model_profile` | Yes | No | Configuration-only by contract; no model weights; evaluator not implemented |
| `route` | Yes | No | Configuration-only by contract; evaluator not implemented |

Unsupported labels fail G5. A future implementation must add an exact mutable
surface, deterministic fixture, executable evaluator, evidence binding, and
activation policy before changing that behavior.

## Evidence freshness ledger

Current checkpoint evidence:

- Issue #70 CodeCairn formal experiment
  `1c5496edfaa08212635f6218f9aaa55c3e942fcd1e79203a11a6b8c4d9b94623`
  at Pico `5318daa` and CodeCairn `a501fe2`: 32/32 terminal Trials,
  16/16 valid Pairs, 16/16 treatment task passes versus 0/16 control passes,
  Recall@5 1.0, zero stale injections, zero cross-repository leakage, and zero
  Memory-off backend operations. The result is ship-complete and
  measurement-valid, but `positive_claim_eligible=false` because every
  hard-negative query returned three memories. The Provider ledger charged
  0.91294224 CNY; 10.91294224 CNY total committed includes a fixed 10 CNY
  reserve and is not a Provider invoice.
- PicoBench semantic v2 experiment
  `98bb1e3cca2d1ee45dbebebef7f44db87fbea8ea23d1ea177843df6ba3ca2a1b`
  at `e6c790e`: 260/260 records, including 200 production EverOS retrieval
  records and 60 Local-only BM25 controls. Memory Recall@1 and Precision@1
  were 1.0; fused Skill candidate Recall@10 was 1.0 versus 0.625 per single
  source. The evidence stage is candidate retrieval, not final Skill
  injection.
- PicoBench Ship-1 experiment
  `abffb7d2fe6a76f1102741cacd3cff1ed02697be0fb37fe2fa7a910dbeb11b4d`
  at `e6c790e`: 216/216
  real-Provider Trials and 260/260 deterministic Retrieval Cases reached
  terminal records. The report is measurement-invalid because one Context Pair
  lacks complete usage evidence. Tool disclosure reduced estimated visible
  Schema tokens by 93.4513 percent across six measurable tasks but regressed
  task pass count from 23/24 to 20/24, so no positive main-campaign metric is
  eligible.
- Issue #21 closure (2026-07-27): required V-LF passed five live phases against
  the real Pico Feishu bot; the optional second-actor case was skipped and its
  allowlist criterion remains explicitly deterministic through V-C0.
- PR #56 (`b215c13`): V-E0 319 passed; retained deterministic suite 3567
  passed and 52 deselected; small-real setup and lifecycle were verified, but
  no real model run was performed.
- PR #54 (`48a318f`): a fresh V-P0 wheel fed the deterministic installed-host
  Gate, which passed 1 test; live DeepSeek V-LP passed 1 test.
- PR #51 (`df77310`): V-TE0 passed.
- PR #50 (`f46651d`): V-C0 passed 387 contract tests; V-S0 passed 35 named
  security selections; V-P0 passed.

Relevant older evidence:

- PR #47: V-O0 passed 134 deterministic checks plus one required live EverOS
  check; V-E0 was then 301 and the retained suite was 3311 passed, 46
  deselected, 11 warnings.
- PR #43: installed CLI/TUI/Gateway parity and an earlier live DeepSeek run.
- PR #42: V-P0 distribution proof with 67 successful command probes.

Older results remain useful history but do not prove a later commit. In
particular, no real small-real outcome or complete V-R0 report is recorded for
current `main`.

The default GitHub CI is intentionally smaller than release acceptance. It
does not run every deterministic, package, live, continuity, Channel,
correlation, Evolver, dependency, and release layer on every PR. V-R0 is the
mechanism that must aggregate those layers on one clean release commit.

## Open problems

### P0: release blockers

1. **The small-real Evolver run has not been executed with a real model.** The
   subject, immutable grader, setup, check, resume, finalize, and deterministic
   lifecycle are present. An accepted, rejected, or reproducible
   no-improvement outcome is still required; Provider or infrastructure
   failure is not a valid product result.
2. **There is no release candidate.** The V-R0 driver exists, but the complete
   Gate has not passed on one clean commit. There is no Pico version bump, tag,
   release artifact set, or enabled publication workflow. Its
   `memory_continuity` layer remains inconclusive until the compatible Myna
   distribution is formally available. Issue #24 owns the release closure.

### P1: implementation and architecture debt

- `DeliveryHub` emits `channel.deliver` spans and can publish a
  `DELIVERY_FAILED` notice through an injected sink, but hosts do not yet wire
  that sink. The outbound queue is in memory, and a failed send does not
  retroactively fail a completed Turn.
- `DeliveryHub.aclose()` cancels workers and does not guarantee an in-flight
  send is flushed.
- Session, Curator, Myna, Tracing, Cron, and Evolution Run stores are not
  one transaction.
- Only `runtime` candidates can pass G5; the other Candidate Labels remain
  fail-closed.
- The AppWorld example is checkout-loaded. The tracked small-real benchmark
  instead owns its plugin in a disposable subject repository.
- The direct Sandbox executes on the host. Candidate execution should remain
  isolated in a disposable container or VM with scoped credentials.
- Candidate digests are tamper-evident for a cooperative local workflow, not
  signed attestations.
- Tracing is local and best-effort rather than a multi-process durable ledger.
- The source-tree weather Skill is not included by the current wheel allowlist.
- Current CI remains smaller than the release acceptance model.

### P2: deliberate scaling deferrals

- Full-size, multi-round Evolution Runs have not been exercised for a Pico
  release.
- Zero-hit preflight is off by default; borrowing and affinity selection are
  not fully wired. They should land only when measured benchmark cost justifies
  them.
- QQ and WeCom remain Beta until later adapter-specific live evidence passes.
- No standalone observability web product is planned. The local viewer is an
  operator aid, not a hosted control plane.

## State and compatibility boundaries

| Scope | Default |
| --- | --- |
| Global config and Runtime data | `~/.pico` |
| Foreground Workspace | Current directory |
| Foreground Workspace State | `~/.pico/projects/<project-id>` |
| Gateway / configured Workspace | `~/.pico/workspace` |
| Myna repository binding and state | Myna-owned configuration selected by `myna init` |

Pico does not automatically import external product state. Pointing `--config`
or `--workspace` at another path is explicit direct use with colocated state at
that path, not migration.

The Myna operator contract requires an explicit `myna init` and keeps Myna
state under the Myna-owned runtime root. Pico does not automatically initialize,
scan, migrate, rewrite, or delete Myna data or data left by removed integrations.

## What “v1 complete” means

The approved product contract requires one release commit and its fresh
artifacts to demonstrate:

1. a real Provider through installed CLI, TUI, and Gateway;
2. Session continuity plus the currently selected Memory backend's
   commit-bound installed continuity evidence;
3. Cron execution through Spine;
4. real Feishu inbound and outbound delivery;
5. correlated Turn traces, usage, terminal state, and delivery;
6. a small real Evolution Run with an explicit verdict and rollback boundary;
7. the complete V-R0 dependency, provenance, package, asset, and release
   aggregation.

Accepted, rejected, or reproducible no-improvement is a valid real candidate
outcome if the run and evidence are complete. Provider, Channel, or
infrastructure failure is not a successful product result.

## Links

- [Product contract, Issue #1](https://github.com/Hackerismydream/pico-harness/issues/1)
- [Feature-to-evidence matrix](feature-evidence.md)
- [Committed roadmap](roadmap.md)
- [Architecture](architecture/README.md)
- [Evolution history](evolution.md)
- [Developer Gates](dev.md)
