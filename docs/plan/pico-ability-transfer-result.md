# Pico + Myna Evidence-Driven Evolution Result

Status: completed controlled evaluation on 2026-08-31.

## User-visible story

A user completes an ordinary Pico task. Pico records the Turn result, Tool
receipts, file changes, verification commands, and delivery outcome. Myna
stores that evidence as repository-scoped Task Experiences. When three
independent verified Experiences describe the same Ability, Myna compiles a
versioned instruction-only Ability Card from the exact bound Source Facts.

The candidate is created automatically, but production authority is not. A
candidate remains pending until its evidence and activation receipt satisfy
the configured policy. On a later task, Myna Recall returns relevant active
candidates, Pico combines them with its other Skill sources, and a fail-closed
LLM Gate may select an exact revision for Context injection. Unknown IDs,
Provider failures, malformed Gate output, and missing trigger conditions
abstain. The next independent task verifier, rather than the model's own text,
determines whether the learned Ability helped.

```text
ordinary Pico task
  -> evidence-backed Task Experience in Myna
  -> repeated verified Ability group
  -> Source-Fact-preserving Ability Card revision
  -> evidence and human/evaluation activation receipt
  -> Myna Recall
  -> Pico exact-ID LLM Gate
  -> later task and independent verifier
```

## Controlled experiment

The suite contains six Pico repository Abilities, 18 learning instances, 24
identity-disjoint held-out implementation tasks, and 24 confusing negative
queries. Model, task prompt, fixture, tools, execution limits, and verifier are
held constant inside every pair.

Stage A isolates learned content by routing the exact automatically compiled
Myna Ability Card to its known Ability. Across 48 paired held-out evaluations,
NoSkill passed 15 and the Myna Skill arm passed 26: a +22.92 percentage-point
delta with a task-clustered 95 percent interval of [+8.33, +39.58]. All 96
trials were measurable and the offline verifier passed.

Stage B evaluates the automatic Recall and Pico Gate path. Across another 48
paired evaluations, Control passed 15 and automatic Recall + Gate passed 24: a
+18.75 percentage-point delta with a task-clustered 95 percent interval of
[+6.25, +33.33]. All 48 pairs were valid, there were zero treatment
regressions, and the Gate injected an exact revision in 40 of 48 treatment
trials. The offline verifier reconstructed the manifest, candidate snapshots,
raw outcomes, aggregate, claim, inventory, and complete CNY 1.6420908 Provider
ledger.

The confusing-negative check found eight Recall candidates. The Gate rejected
six and selected two adjacent-but-out-of-scope candidates. Therefore the
task-effect measurement is valid and statistically positive, while automatic
production activation remains disabled pending a stricter trigger Gate. This
separates demonstrated learning value from deployment authority.

## Resume wording

Designed and implemented an evidence-driven Pico + Myna evolution loop that
turns verified ordinary-task traces into repository-scoped, versioned Ability
Cards and reuses them through Recall plus a fail-closed exact-ID LLM Gate. Built
a six-Ability, 24-task paired A/B suite with independent verifiers; the
end-to-end path improved pass rate from 31.25% (15/48) to 50.00% (24/48), a
+18.75 percentage-point lift with a task-clustered 95% CI of [+6.25, +33.33]
and zero paired regressions.

## Interview answer

The problem was that an Agent could finish one task but would start the next
similar repository task from scratch. I split self-evolution into two systems.
Pico owns execution evidence and independent task verification; Myna owns
repository memory, repeated-experience grouping, and versioned Ability Cards.
The compiler receives the exact Source Facts behind verified tasks, so it must
preserve decision tables, accepted and rejected inputs, and failure boundaries
instead of writing generic advice. On the next task, Recall proposes a
candidate and Pico's Gate can inject only an exact revision whose trigger and
tool requirements match.

To show this was not random prompt injection, I froze 18 learning examples and
24 disjoint held-out tasks across six real Pico policies, then ran paired A/B
tests with the same model, prompt, tools, limits, and independent verifier. The
automatic end-to-end path increased verified pass rate from 15/48 to 24/48,
with a +18.75 percentage-point lift and a 95 percent confidence interval whose
lower bound was +6.25 points. I also tested 24 confusing negative queries. The
remaining two false selections are why learned candidates can be generated and
recommended automatically, but production activation still requires evidence
and human authority.

## Evidence identity

- Pico commit: `e8eeea261c65d2e69d3f8977fecdb40c09891ae9`
- Myna commit: `8d513e3ff8ef62ef9c90fba1d0626b18e402d07f`
- Stage A approval digest:
  `6592ddcc8227b74fff75e32f379de02d62e377e9cf7272404e6582ea06f823ab`
- Stage B approval digest:
  `1869e0a4aa50562aefb98257a32a760481d10163c1c5042a657e54a576ca94e8`
- Stage A local evidence:
  `.pico/evidence/pico-ability-transfer/stage-a-v4-formal`
- Stage B local evidence:
  `.pico/evidence/pico-ability-transfer/stage-b-gate-v7-formal`
