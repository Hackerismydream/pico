# Codex Goal: turn negative Skill transfer into a measured improvement

Status: authorized for implementation and staged Provider-backed evaluation on
`feat/verified_skill_evolution`. The combined Provider hard cap is CNY 25. A
stage may stop below its cap, but completed Trial subsets cannot be selected
after results are visible.

## Objective

Build `skill_transfer_v2` across Pico and Myna. The new method must separate
three decisions that `skill_transfer_v1` combined:

1. whether learning-side knowledge is useful to the held-out task;
2. whether a recalled candidate may influence the current Turn; and
3. whether the injected instructions create new verified successes.

The user path remains an ordinary Pico Turn. Myna may capture and derive a
draft Skill asynchronously, but Recall returns only a candidate. Pico owns the
per-Turn decision to inject it. A failed selector abstains. Automatic Skill
activation remains disabled until the exact automatic method passes the frozen
formal experiment.

## Starting evidence

The completed v1 experiment is valid negative evidence:

- 96/96 primary Trials and 48/48 valid Pairs;
- Control 32/48 and Treatment 25/48;
- verified pass delta -14.58 percentage points;
- task-clustered 95 percent interval `[-31.25, 0]`;
- 3 paired gains and 10 paired regressions;
- 24/24 obvious hard negatives with zero incorrect injections; and
- CNY 2.16426315 charged with offline-rebuildable artifacts.

V2 does not rewrite that result. It introduces new schemas, artifacts, Trial
identities, and Claim Rules.

## Causal hypothesis

V1 promoted a weakly relevant candidate directly into system instructions.
Myna merged many useful boundaries into one long Skill, while Pico activated a
Memory-derived Hit without a second applicability decision. Treatment consumed
about 3,751 more input tokens per Trial and made fewer useful Tool calls.

V2 tests these explanations in order:

```text
short, oracle-routed knowledge helps?
  no  -> stop: task/model/budget is unsuitable for Skill transfer
  yes -> can a fail-closed Gate remove forced-injection regressions?
           no  -> content remains the limiting factor
           yes -> can the automatic compact compiler reproduce the gain?
                    no  -> compiler remains unfit for activation
                    yes -> automatic method is eligible for a formal claim
```

## Product interfaces

### Pico Skill selection

`SkillsSegmentBuilder` remains the deep module used by Context assembly. Its
interface accepts the existing Router plus optional Query Rewriter and Gate.
It owns this sequence:

```text
task -> optional rewrite -> Router candidates -> deterministic resolution
     -> Gate decision -> optional wrapper -> rendered # Skills + evidence
```

Memory-derived Skills carry `gate_required=true`. A Gate call may select zero
or one exact candidate. Provider failure, timeout, malformed JSON, duplicate or
unknown ids, and over-limit output produce an abstention for gate-required
candidates. Operator-managed Local Skills preserve their existing explicit-use
path and do not silently lose availability during a Gate outage.

The Gate returns a structured decision containing status, one-sentence plan,
candidate ids, selected ids, and stable reason codes. The decision is evidence;
its plan is never shown to the main Agent.

Selected derived Skills are wrapped as optional strategies. The task statement,
repository state, Tool results, and Verifier requirements take priority. The
wrapper explicitly rejects unrelated engineering work mentioned by the Skill.

### Myna compact compiler

Myna keeps immutable v1 records readable. New v2 revisions use a compact
instruction-only content contract:

- description at most 160 characters;
- at most three triggers;
- at most three required procedure steps;
- at most two conditional avoidance rules;
- at most two executable verification actions;
- at most four required capabilities; and
- at most 500 estimated tokens for the rendered Skill body.

Every trigger, procedure, avoidance, and verification rule binds one or more
allowed learning-side Fact or Experience aliases. Unknown or missing bindings,
overflow, executable assets, and unrecognized fields reject the candidate.
Myna still owns repository scope, eligibility, identity, provenance, revision,
and lifecycle. The semantic Provider proposes text and allowed aliases only.

Existing draft, activation receipt, active head, rejection, Supersession, and
rollback behavior is reused. New v2 drafts do not change the current active
head until a separate receipt accepts them.

## Evaluation protocol

### Shared controls

Every stage freezes the following before Provider execution:

- candidate Pico and Myna commits and wheel digests;
- learning, held-out, obvious-negative, and confusing-negative digests;
- Provider, model, prompt, Tools, repository fixtures, timeout, retries, and
  Iteration budget;
- exact arm definitions and Gate prompt revision;
- independent Verifier implementation and success definition;
- bootstrap unit, seed, samples, and confidence level;
- stage budget and complete-matrix stop rule; and
- raw outcome, receipt, budget, runtime snapshot, and inventory schemas.

Learning, held-out, and negative instances remain identity-disjoint. Candidate
generation never receives held-out prompts, fixtures, trajectories, or
Verifier outputs. A Runtime change requires a fresh Control.

### Stage A: knowledge upper bound

Arms for 24 held-out tasks, two repetitions:

- `no_skill`: no Skill path;
- `long_skill`: the v1 automatic Skill with oracle ability routing;
- `anchor_skill`: a maintainer-authored 300 to 500 token Skill built only from
  the learning projection, also with oracle ability routing.

This produces 144 primary Trials. Anchor results are diagnostic and can never
support an automatic self-evolution claim.

Continue only when `anchor_skill - no_skill` has a task-clustered 95 percent
interval whose lower bound is above zero. If JSONL remains 0 in both arms, it
is marked `capability_floor=true` but remains in the intention-to-treat total.

Stage A Provider hard cap: CNY 3.50.

### Stage B: selection authority

Use the unchanged v1 long Skill with three arms:

- `no_skill`;
- `gate_shadow`, which records one immutable Gate receipt but injects nothing;
- `gate_inject`, which references that same receipt and injects only the exact
  selected Skill.

The primary effects are:

- `gate_inject - gate_shadow`: effect of Skill text after the selection
  decision already exists; and
- `gate_inject - no_skill`: end-to-end product effect including Gate cost.

Gate Provider usage, latency, failures, abstention, coverage, selected
precision, false-positive injection, and false-negative abstention are charged
to Treatment. Add four confusing negatives per ability whose vocabulary is
similar but whose required operation conflicts with the Skill.

Stage B Provider hard cap: CNY 4.50.

### Stage C: automatic compact method

Repeat the same three-arm design with Myna v2 compact Skills. Use three
repetitions for 216 primary Trials and 48 negative Gate evaluations.

A positive automatic-method claim requires:

- every planned Trial and Pair complete and valid;
- zero split overlap and complete candidate provenance;
- task-clustered 95 percent interval lower bound above zero for
  `gate_inject - no_skill`;
- task-clustered 95 percent interval lower bound above zero for selected-task
  `gate_inject - gate_shadow`;
- each ability above a preregistered non-inferiority floor of -12.5 percentage
  points, equivalent to at most one net loss in eight paired observations;
- zero incorrect injections on obvious negatives and at most one across the
  complete confusing-negative matrix;
- complete Gate and Agent resource observations; and
- offline reconstruction of aggregate, claim, budgets, receipts, runtime
  snapshots, and inventory.

Stage C Provider hard cap: CNY 7.00.

### Stage D: retrieval and AgentCase

Stage D is out of the critical path until Stage C passes. It separately tests
lexical, sparse+dense, rerank, Skill-only, Case-only, Skill+Case, and Neither.
No Stage D result may be attributed to Skill alone unless the factorial arm
supports that contrast.

Stage D and reserve hard cap: CNY 10.00. The total across all stages remains
CNY 25.

## Delivery slices

1. Add Pico Gate decision and failure-policy tests, then implement the smallest
   compatible decision interface.
2. Wire Rewriter and Gate into `SkillsSegmentBuilder`; add integration tests for
   Memory-required gating, Local fallback, optional wrapper, and evidence.
3. Add the Stage A corpus, Anchor Skills, manifest, runner, aggregate, budget
   ledger, and offline verifier; run credential-free tests before live Trials.
4. Run Stage A once. Stop on its preregistered result.
5. If Stage A passes, add Myna v2 compact records and compiler one behavior at
   a time: limits, source aliases, rendering, durable parsing, lifecycle, and
   agent-track Recall.
6. Add Stage B/C immutable Gate receipts, three-arm execution, confusing
   negatives, aggregate, and Claim Rules.
7. Run Stage B, then Stage C only if the preceding diagnosis supports it.
8. Run both repositories' authoritative checks, review the complete diffs,
   commit complete slices, synchronize with latest `main`, rerun after any
   rebase, push, create PRs, wait for required checks, and land only when no
   high-impact finding remains.

## Interview boundary

Before Stage C passes, the accurate story is that V1 exposed a negative
transfer failure, the team isolated selection authority from memory storage,
and V2 is being evaluated. Only a passing frozen Stage C may fill in the final
Control, Treatment, confidence interval, negative-injection, and cost numbers
in a resume or interview claim.
