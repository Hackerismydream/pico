<!--
Snapshot source: project-tutorial-writer/references/gold-examples.md
Snapshot date: 2026-09-02T09:38:10.120Z
Purpose: make the Pico tutorial-writing guidance readable from GitHub.
-->
# P00/P01/P05 calibration examples

These examples capture accepted teaching moves. Reuse the decisions, not the exact headings or sentence shapes.

## Contents

- [P00: overview through one message](#p00-overview-through-one-message)
- [P01: assembly after the reader knows what it enables](#p01-assembly-after-the-reader-knows-what-it-enables)
- [P05: architecture as a design derivation](#p05-architecture-as-a-design-derivation)
- [Why the accepted shapes differ](#why-the-accepted-shapes-differ)
- [One accepted architecture-essay composition](#one-accepted-architecture-essay-composition)
- [What remains free](#what-remains-free)
- [Reusable edit decisions](#reusable-edit-decisions)

## P00: overview through one message

Accepted opening pattern:

> A learner sends one concrete request through a real entry such as Feishu. The chapter names the visible reply, then summarizes the path with six ordinary verbs before introducing internal types.

Why it works:

- The reader knows who did what and what completion looks like.
- The code compass follows request order: Channel, Intake, Scheduler, Agent Loop, Session, Delivery.
- `TurnRequest`, `Lane`, `Iteration`, and `DeliveryHub` appear when the request reaches them.
- Execution completion and delivery completion become understandable because the reader has already watched both events happen.
- Each diagram appears beside the mechanism it summarizes rather than in a front-page gallery.

Avoid this overview pattern:

```text
Pico is a unified Agent Harness composed of Runtime, Context Engine, Memory,
Skills, Tool Registry, MCP, Scheduler, Delivery, Tracing, Evaluation...
```

It is fact-rich but gives a beginner no path through the nouns.

## P01: assembly after the reader knows what it enables

Accepted transition pattern:

> The previous chapter follows a message. The assembly chapter steps back and asks who created and connected the objects before that message arrived.

Why it works:

- The need for assembly comes from a path the reader already understands.
- The first object example says which two or three fields matter now and which details can wait.
- Startup is explained as creation, asynchronous start, connection, readiness, and cleanup.
- Workspace and state are explained through where code work and runtime records actually go.
- Ownership tables answer who creates and closes each resource.

Do not copy these accidental patterns:

- five or more learning questions at every opening;
- a `记住一句话` block after every section;
- mandatory 1.5x-2x expansion;
- the same number of stages in unrelated chapters;
- a fake personal story presented as real experience.

## P05: architecture as a design derivation

Accepted reasoning pattern:

> A tool may have changed the workspace before the process saved its result.
> The chapter separates Session, Context, Workspace, in-process execution, and
> external effects, rejects the assumption that one archive can represent all
> of them, compares harnesses through shared recovery questions, then states
> Pico's recovery contract before explaining JSONL, consistency fences, and
> checkpoints.

Why it works:

- Beginner questions remove the three central misconceptions before internal
  names appear: restored transcript is not the model's entire context, a
  historical tool call is not a replay queue, and resume does not revive the
  old call stack.
- The naive JSON snapshot remains a reasonable hook, but the analysis moves
  from the carrier to its hidden assumption: one record cannot speak for state
  owned by different systems and commit boundaries.
- Pi, OpenCode, and Claude Code are compared through common responsibilities,
  leaving a reusable design model after product names are removed.
- Pico's guarantees and explicit non-guarantees appear before implementation
  details, so conservative mechanisms read as engineering choices rather than
  arbitrary code.
- The local priority rules make conflicts decidable: preserving recorded facts
  wins over automatic continuation, and explicit failure wins over speculative
  repair. These are P05 decisions, not slogans to copy into other chapters.
- Pico's own solution is restated as stable responsibilities such as Session
  identity, durable journal, Context projection, Workspace evidence, recovery
  policy, and consistency fences. Current files then prove that model instead
  of defining it.
- Each mechanism answers a fault: append versus rewrite, lock versus epoch and
  content freshness, Session evidence versus workspace checkpoint evidence.
- The verification section maps one fault experiment to one earlier promise
  and separates current tests, source-order inferences, and future capabilities.

Do not copy these accidental surface patterns:

- nine sections in every architecture chapter;
- question headings for every subsection;
- a state-domain table when the subsystem has only one meaningful owner;
- an industry survey when no real design choice depends on it;
- the same priority slogans, callout rhythm, or final summary sentence.

## Why the accepted shapes differ

Read these as coherence traces, not prose templates:

| Chapter | Reader gap | Semantic center | Dependency boundary | Movement discovered |
| --- | --- | --- | --- | --- |
| P00 | The reader sees many runtime components but cannot connect them to one completed turn | The harness becomes understandable when one request is followed through changing owners to a visible reply | Action before payload, payload before owner transition, execution completion before delivery completion | Linear request path |
| P01 | The reader knows the runtime path but not how its objects become available or get cleaned up | Assembly is a lifecycle and ownership problem that exists to make the known runtime path possible | Known request path before creation, start, connection, readiness, and cleanup | Step back from a familiar turn into object lifecycle |
| P05 | The reader assumes one archive can represent the entire interrupted system | Recovery crosses independently owned state and commit boundaries, so restoration needs an explicit contract and bounded evidence | State distinctions before failed snapshot assumptions, contract before mechanisms, claims before fault evidence | Design derivation with a conditional industry comparison |

The chapters look different because their semantic centers, dependency
boundaries, and expressive choices differ. Reusing the same headings would
erase the reason each chapter works.

## One accepted architecture-essay composition

P04 and P05 happened to produce a readable order similar to this:

```text
one real problem and a useful analogy
-> plausible naive solution and the assumptions exposed by failures
-> industry design space, only when a later choice depends on it
-> project contract and guarantee priorities
-> stable responsibilities independent of current names and carriers
-> one complete normal path
-> mechanisms, trade-offs, and evidence organized by engineering question
```

This is evidence that one topic admitted this composition. It is not the
default outline for an architecture chapter. The finished prose may preview a
later failure, delay a definition, return to an earlier image, or move evidence
away from first mention while preserving dependency safety. Omit, combine,
split, or move any element when the new chapter's reader state, semantic center,
domain model, and evidence invite a different movement.

## What remains free

The calibration examples do not determine:

- whether the opening is a task, failure, image, question, result, or source
  detail;
- whether an idea is explained immediately or planted and resolved later;
- paragraph length, sentence rhythm, amount of dialogue, or authorial voice;
- how often the chapter leaves and returns to its central question;
- whether evidence appears beside first mention or at the moment trust becomes
  necessary;
- whether the ending summarizes, tests a new case, returns to the opening, or
  deliberately leaves a bounded question open.

Reuse a visible move only when the new chapter has the same reader problem.
Otherwise preserve the underlying judgment and let the prose find another
form.

## Reusable edit decisions

| Reader problem | Editing decision |
| --- | --- |
| Too many names before any action | Start with one task and delay names until first use |
| No idea where to open the repository | Add a small request-ordered code compass early |
| Initialization breaks the flow | Finish the runtime path first, then step back to setup |
| Failures rely on a normal model the reader does not have | Complete the relevant normal path before expanding those branches |
| Diagrams are collected at the top | Move each diagram to the paragraph that needs it |
| Dense object or payload | Tell readers which fields to read now |
| Repeated boundary disclaimers | Replace them with owner, action, output, and applicability |
| Every section has identical cadence | Keep only structure required by this mechanism |
| Source files determine the chapter order | Derive movement from the reader's question; use source to reveal or prove mechanisms |
| Plausible naive solution is dismissed too quickly | Name its hidden assumptions and test them against ownership and failure boundaries |
| Industry section reads like a product catalog | Ask every harness the same questions and extract design coordinates |
| Tests appear as an appendix | Map each experiment back to one earlier guarantee |

The gold standard is reader orientation plus source truth. Surface voice may vary across authors and chapter types.
