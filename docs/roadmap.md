# Pico roadmap and future

This document explains the current Pico v1 delivery order. GitHub Issue #1 and
the open issue bodies are authoritative for acceptance details. "Future
candidates" are recommendations, not committed scope.

## Current checkpoint

Issues #2-#23 are complete. The groundwork for Issue #24 has also landed:

- PR #48 added V-C0 and the fail-closed V-LF live Feishu harness;
- PR #49 remediated release-path dependency findings;
- PR #50 completed the QQ and WeCom deterministic Beta contract;
- PR #51 completed V-TE0 Turn evidence correlation;
- PR #52 added the V-R0 release driver;
- PR #53 added the implementation learning path and feature-evidence matrix;
- PR #54 refreshed V-P0 consumption and live DeepSeek V-LP;
- PR #56 added the tracked small-real Evolver subject and deterministic
  lifecycle harness.
- PR #57 documented the current architecture and release order.
- Issue #21 completed the required real Feishu V-LF run and promoted the
  adapter evidence level to live-gated.

This checkpoint is still Alpha and pre-RC. A harness existing is not the same
as a live run passing. See [Project status](project-status.md) and
[Evolution history](evolution.md).

The separate Pico Harness v0.1 portfolio/engineering milestone is complete:
the Runtime, Context, Memory/Skill, Tool/MCP, and PicoBench Ship-1 body is a
coherent reviewable project. This milestone is not the package version, formal
Pico v1, a full V-R0 pass, or a positive main-campaign uplift.

## Committed dependency graph

```text
Issue #21: real Feishu V-LF passed ─────────────┐
                                                ├─> full V-R0 on one clean commit
Issue #24: complete real small-real verdict ───┘       -> version, tag, release
```

Issue #22 is closed by PR #50. Issue #23 is closed by PR #51. Issue #21 is
closed by its required V-LF evidence run. The remaining work is the small-real
verdict and release closure, not another broad Runtime rewrite.

## Stage A: real Feishu Gate completed

[Issue #21](https://github.com/Hackerismydream/pico-harness/issues/21) owned the
required production tracer bullet. The V-LF harness is implemented in
`scripts/verify_live_feishu.py` and
`tests/integration/test_feishu_real_channel.py`; PR #54 corrected its
fail-closed Memory configuration before the first live run.

The required run passed on 2026-07-27 against the real Pico Feishu application
and recorded:

- inbound dispatch, allowlist and group policy, duplicate suppression, and
  reconnect behavior;
- submission through `Intake -> Spine -> AgentTurnRunner -> AgentLoop`;
- outbound reply through `DeliveryHub -> ChannelOutletAdapter -> Feishu`;
- one inbound attachment and one outbound `MediaOut`;
- a persisted Cron job claimed once after Gateway restart and delivered to
  Feishu;
- redacted, rerunnable evidence bound to the exact commit and scenario.

Recorded evidence:

- V-C0 and V-S0 remain green;
- V-LF passed in required mode;
- the historical EverOS V-O0 result remains bound to its old commit and is not
  current Myna continuity evidence.

A mocked SDK, recorded payload, missing credential, skipped case, Provider
failure, or infrastructure failure does not satisfy V-LF. The passed report
binds Feishu's live-gated claim to the exact commit and scenario it records.

## Stage B: complete one real small-real Evolution Run

[Issue #24](https://github.com/Hackerismydream/pico-harness/issues/24) owns the
release candidate and consumes the tracked
`benchmarks/evolver/small_real.yaml` path landed in PR #56.

The deterministic harness already provides:

- a disposable subject template with a fixed train/sealed split;
- an immutable grader and Candidate Manifest mutable boundary;
- setup, precheck, smoke, interrupt, resume, status, finalize, and evidence
  tests;
- fail-closed source validation and infrastructure classification.

What remains is a real model-driven run. It must use a disposable subject
checkout and external work directory, preserve the sealed boundary, and
produce an explicit evidence-bound verdict. `accepted`, `rejected`, or
reproducible `no_improvement` can be valid. Provider or infrastructure failure
cannot be relabeled as no improvement or completion.

Activation remains manual. The run must not modify the live Pico checkout.

## Stage C: close V-R0 and publish Pico v1

The V-R0 driver landed in PR #52. It runs thirteen layers in dependency order
and rejects missing, stale, dirty, skipped, or unbindable evidence. A subset
run is diagnostic and can never report a passed release. The
`memory_continuity` layer remains inconclusive until the compatible Myna
distribution is formally available and the installed composition can be
reproduced without a local filesystem dependency.

The final release commit must run:

- V-D0 retained deterministic suite;
- V-T0 TUI checks and bundle;
- current-commit V-P0 distribution;
- deterministic installed-host parity and V-LP real Provider;
- V-C0 and V-S0 Channel contracts;
- V-LF real Feishu;
- the Myna installed-composition Gate;
- V-TE0 Turn evidence correlation;
- V-E0 Evolver;
- dependency audit, provenance, and repository-asset checks;
- the real small-real Evolution Run.

Exit condition:

1. `make verify-release` passes on a clean commit and writes its indexed,
   commit-bound report.
2. Project status, feature evidence, release notes, version metadata, and
   maturity labels describe exactly that result.
3. The same commit is tagged and its wheel, source distribution, checksums, and
   release notes are attached to the Pico release.

Older PR artifacts remain historical evidence. They cannot be assembled by
hand into a current V-R0 pass.

## PicoBench CV metrics track

PicoBench Ship-1 is the implemented checkout-only track for turning current
Runtime, Context, Memory/Skill, and Tool/MCP behavior into reproducible task
results. GitHub Issue
[#59](https://github.com/Hackerismydream/pico-harness/issues/59) accepted the
scope. The contract is in
[Agent application evaluation](evaluation/README.md), and the implementation
slices are indexed in [docs/plan/tasks](plan/tasks/README.md).

The tracked implementation supplies:

- one Provider/model campaign with a cumulative CNY 100 cost ceiling;
- frozen tasks, external deterministic Verifiers, and treatment axes;
- the authorized optional `context_engine_factory` seam in Agent Loop, Runtime
  Assembly, and Context factory;
- Runtime R0/R1 claim boundaries;
- failure classification, Pair coverage, and statistical rules;
- the separation of Ship completeness, Measurement Validity, and Positive
  Claim Eligibility.

The final-history Ship-1 campaign recorded 216/216 terminal real-Provider
Trials, 260/260 deterministic Retrieval Cases, and 119/120 valid single-axis
Pairs. It is ship-complete but measurement-invalid because one Context Pair
lacks complete usage evidence. Progressive Tool disclosure reduced equal-task
macro estimated visible Tool Schema tokens by 93.4513 percent across six
measurable tasks, but treatment task passes regressed from 23/24 to 20/24.
No main-campaign positive metric is eligible.

The historical held-out semantic v2 addendum recorded 260/260 cases: 200 used
the former production EverOS retrieval path and 60 are Local-only BM25
controls. Memory
context-injection Recall@1 and Precision@1 are both 1.0, and fused pre-gate
Skill candidate Recall@10 is 1.0 versus 0.625 for each single source. Final
Skill injection, raw hard-negative abstention, and end-to-end Memory task
improvement remain outside those claims.

Generated campaign reports remain outside Git. A PicoBench implementation or
completed negative measurement does not imply a positive claim; only eligible
improvement metrics from the frozen campaign may be copied into project or
resume claims. Deterministic R0/R1 Runtime invariants may be quoted separately
only with their explicit evidence scope.

This track is not part of the committed Issue #24 to V-R0 graph.
Ship-1 is not a generic Evaluation Framework, a public CLI feature, a recovery
protocol, an Evolver verdict, or a V-R0 substitute. Its different single-axis
controls must not be combined into one Pico-full overall-lift claim.

## Future candidates after v1

These items are intentionally uncommitted. Each needs a product reason, an
issue, an exact acceptance Gate, and evidence before implementation.

### F1: stabilization and release engineering

Highest-value post-v1 direction:

- Linux and macOS installed-wheel matrix;
- long-running Gateway, Channel reconnect, Cron restart, and claim-recovery
  soak;
- config upgrade and state-corruption characterization;
- dependency and vulnerability closure policy;
- signed release provenance, SBOM, and artifact checksums;
- remote CI jobs for deterministic full-suite, distribution, and Evolver
  Gates;
- explicit retention and redaction policy for live evidence.

Why first: these deepen already-retained behavior and reduce the gap between a
portfolio demo and an operable Runtime.

### F2: production promotion for QQ or WeCom

Promote one adapter at a time only after:

- a real bot environment;
- redacted inbound and outbound artifacts;
- reconnect and rate-limit recovery;
- media round trip;
- restart-surviving Cron delivery;
- the same evidence classification used for Feishu.

The Beta contract from Issue #22 remains valuable even if production access is
not immediately available.

### F3: enable one additional Candidate Label

Do not implement all five unsupported labels for symmetry. Pick the label with
the strongest real use case, probably `prompt` or `skill`, and require:

1. an exact mutable surface;
2. a deterministic fixture;
3. an executable evaluator;
4. a G5 label policy;
5. train/held-out evidence separation;
6. activation and rollback semantics;
7. one real, reviewable candidate outcome.

`model_profile` and `route` remain configuration-only. No label authorizes
model-weight mutation.

### F4: larger Evolution Runs and statistical calibration

Only after the small real release run:

- run multiple rounds and enough trials to calibrate Gate-f and paired
  significance;
- characterize Provider drift and same-session controls;
- measure when zero-hit preflight, borrowing, or affinity selection saves real
  cost;
- add those mechanisms only when the measurements justify their complexity;
- optionally sign evidence bundles if the threat model expands beyond a local,
  non-adversarial operator.

A larger benchmark number is not useful if its subject commit, denominators,
infra exclusions, or held-out boundary cannot be reproduced.

### F5: activation review ergonomics

The current activation API advances artifact state but has no public operator
workflow. A future release may add:

- `pico evolve review`;
- manifest/evidence/diff/retention inspection;
- explicit `ready`, `activated`, and `rolled_back` commands;
- disposable application of a candidate to a new checkout;
- pre-activation Runtime Gate and post-activation rollback drill.

Automatic activation remains out of scope unless the product contract changes.

### F6: evidence and tracing operations

With V-TE0 landed:

- add trace/evidence retention and compaction;
- add cross-process write locking or per-process trace partitions;
- export to an external observability system only through a stable adapter;
- preserve the local, non-interfering facade;
- avoid turning Pico into a hosted control-plane product.

### F7: Context and SkillForge hardening

Potential work:

- make Skill usage feedback meaningful or remove unwired configuration knobs;
- define lifecycle semantics for draft, active, deprecated, and retired Skills;
- verify Skill packaging as part of V-P0;
- expose source failure and selection diagnostics without leaking recalled
  content;
- benchmark Context selection and Skill injection on reproducible long-session
  tasks.

### F8: Sandbox and candidate isolation

The current BoxLite path is useful but the Evolver threat model is not
adversarial. Future hardening may:

- run the designer, candidate, scorer, and sealed evaluator in separate
  containers or VMs;
- use scoped, short-lived credentials;
- default-deny candidate network access except named subject endpoints;
- attest the immutable scorer and evaluation kernel;
- test host and oracle escape attempts.

This should be driven by a stronger threat model, not by renaming heuristic
guards as a secure sandbox.

## Historical Memory milestones and current boundary

### F9: historical EverOS-to-CodeCairn replacement

CodeCairn was Pico's v0.2 Memory milestone. Its implementation and joint
evidence campaign remain immutable historical records; CodeCairn is no longer
the current product backend.

The public result is:

```text
memory.backend = codecairn  # historical configuration, now rejected
memory.backend = null       # retained Memory-off behavior
```

Ownership remains narrow:

- Pico owns Runtime, Session, Context, Tool/MCP, Local Skills, default
  selection, onboarding, base-distribution compatibility, continuity, and
  PicoBench;
- CodeCairn owns repository identity, the append-only Pico Source Journal,
  Trace import, durable Memory, retrieval/packing, and the installed
  `pico.plugins` Adapter;
- Pico has removed the bundled EverOS Plugin, direct dependency, onboarding,
  and remembered-Skill source after the CodeCairn Adapter passed its installed
  contract;
- historical EverOS evidence remains historical and is never relabeled as
  CodeCairn evidence.

Delivery order:

```text
CodeCairn Pico importer                                      completed
  -> CodeCairn installed Memory Adapter                      completed
     -> Pico default switch                                  completed
        -> Pico EverOS deletion and Local Skill verification completed
           -> joint installed continuity and paired evidence completed
```

The historical task slices are:

- [delivery analysis](plan/analysis/codecairn-memory-replacement.md);
- [`codecairn-001` through `codecairn-003`](plan/tasks/README.md).

GitHub Issue #65 authorized and completed `codecairn-001` and `codecairn-002`
at CNY 0. Issue #70 completed `codecairn-003`: the installed M2/M4 Gate passed
and M5 completed 32/32 formal Trials with 16/16 valid Pairs. CodeCairn passed
16/16 task Verifiers versus 0/16 for Memory-off, but the campaign exported no
eligible positive metric because every hard-negative query returned three
memories. Those results are not relabeled as Myna evidence.

### F10: replace CodeCairn with the Myna public seam

Pico now selects `memory.backend = "myna"` by default and consumes Myna only
through the installed `pico.plugins` entry point, `pico-plugin.toml`, and the
generic `MemoryBackend` contract. `memory.backend = null` remains the explicit
Memory-off setting. Retired backend values fail with an actionable error; no
alias, fallback, dual read, or automatic migration exists.

Myna owns repository identity, initialization, journal, index, retrieval,
packing, and `myna://` provenance. Pico owns Agent Harness lifecycle and passes
the normalized before-Turn recall and after-Turn store calls through the public
seam. Pico does not initialize or scan repository history without explicit
operator consent.

The technical installed-composition Gate is implemented, but the compatible
Myna distribution is not yet available from a formal artifact source. Pico
therefore carries no local-path or fabricated remote dependency, and V-R0
continues to fail closed on that single external release blocker.

## Continuing non-goals

Unless the product contract is explicitly revised, the roadmap does not include:

- re-adding non-target Channels;
- restoring Sentinel, autonomous nudging, behavior prediction, or Heartbeat;
- restoring Remote Skill marketplace, Deep Research, or media generation;
- automatic production self-modification;
- model fine-tuning or weight updates;
- web, desktop, or mobile applications;
- enterprise tenants, billing, or hosted administration;
- merging Myna storage or retrieval internals into Pico core;
- retaining EverOS as a hidden fallback or dual-write target;
- optimizing for a predetermined line count.

## Roadmap maintenance

When a future candidate is accepted:

1. create a GitHub issue with scope, dependencies, claim boundary, and Gates;
2. move it into the committed sequence here;
3. update [Project status](project-status.md) only after the implementation
   lands;
4. update [Evolution history](evolution.md) with the merged PR and commit;
5. keep live, deterministic, fixture, historical, skipped, and infrastructure
   results separate.
