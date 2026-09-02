<!--
Snapshot source: project-tutorial-writer/references/writing-rules.md
Snapshot date: 2026-09-02T09:38:10.027Z
Purpose: make the Pico tutorial-writing guidance readable from GitHub.
-->
# Writing rules

## Contents

- [How to use these rules](#how-to-use-these-rules)
- [Target meanings](#target-meanings)
- [Teaching defaults](#teaching-defaults)
- [Lightweight concept reduction](#lightweight-concept-reduction)
- [Preserve the semantic spine](#preserve-the-semantic-spine)
  - [Dependency-safe narration](#dependency-safe-narration)
  - [First-principles derivation](#first-principles-derivation)
  - [Contract and guarantee priorities](#contract-and-guarantee-priorities)
  - [Stable project architecture](#stable-project-architecture)
  - [Mechanism-level reasoning](#mechanism-level-reasoning)
  - [Evidence closure](#evidence-closure)
- [Reader review](#reader-review)
- [Verification checklist](#verification-checklist)

## How to use these rules

Treat factual accuracy, evidence scope, user scope, and the promised reader
outcome as hard constraints. Treat ordering, opening, pacing, placement, and
style guidance as defeasible defaults.

Write a complete draft before applying the review sections. Do not make every
paragraph visibly satisfy a rule. Preserve deliberate suspense, asymmetry,
breathing room, and voice when they improve the reading experience without
weakening the hard constraints.

## Target meanings

Use these operational meanings instead of treating the goals as vague style words.

| Goal | It means the reader can... |
| --- | --- |
| Easy to understand | State the chapter's live question, what changed in their model, and why the next movement matters |
| Deep but accessible | Enter through something concrete, then reach the source objects, data shapes, failures, tests, and evidence the topic requires |
| Less AI-like | Read prose without knowledge dumping, uniform section rhythms, defensive flips, repeated summary slogans, or translationese |

The goal is good teaching, not disguising how the text was produced.

## Teaching defaults

- Reuse a concrete request, operation, or failure while it continues to carry
  the chapter's main question.
- Add a small code compass when the reader needs help continuing the source
  investigation. Order it by the investigation rather than alphabetically.
- Complete a happy path before detailed failures when those failures depend on
  the normal model. Lead with a failure, and leave its answer open, when it
  creates the chapter's real question.
- Introduce a term near first use when early naming would otherwise increase
  cognitive load.
- Put detailed internals after plain-language behavior when the details require
  that behavior. Reverse the order when a surprising implementation detail is
  the most natural entry.
- Add a compact capability preview or screenshot when readers need to see what
  the product already does before the mechanism matters. Keep only behavior the
  chapter later uses.
- Prefer positive ownership language: what receives data, what changes it,
  what owns state, and what the user sees.
- Preserve technical depth through payload shapes, source anchors, invariants,
  failure behavior, and tests rather than front-loading every term.
- Treat diagrams as arguments: establish why the reader should look, guide
  attention to the important relation, and connect the result back to the
  surrounding prose without forcing an identical wrapper each time.

Break any default when the alternative better serves the reader's target
capability without weakening factual or evidence boundaries.

Number a real execution sequence when numbering helps readers keep their place. Avoid numbering rhetorical lists merely to make the prose look organized.

## Lightweight concept reduction

When a mechanism remains confusing, reduce it privately to this shape:

```text
reader action -> incoming data -> owner -> action -> next owner -> visible result
```

Be able to state the mechanism in plain language before asking the reader to
reason with its code vocabulary. The prose may still preview a code name or
unexplained result earlier.

Example:

```text
Plain language: each conversation has one execution line, while different
conversations can run at the same time.

Code vocabulary: conversation -> Lane -> Origin Pool -> TurnRunner
```

Do not use a more abstract concept to explain an already confusing concept.

## Preserve the semantic spine

Derive the reader state, domain model, semantic center, cognitive dependencies,
and evidence map before committing to a form. See
[domain-model-driven-writing.md](domain-model-driven-writing.md) when designing
or substantially reorganizing the chapter.

Use a request path when the explanation mainly follows data and
ownership through a completed operation:

```text
reader action -> owner -> state change -> next owner -> visible result
```

Use a design derivation when the explanation mainly follows a failure, hidden
assumptions, ownership boundaries, competing guarantees, and the mechanisms
chosen in response.

These are possible movements, not fixed chapter sequences. A chapter may braid
them, leave the main line briefly, or return to an earlier scene after the
reader's model changes. The semantic center, not one mandatory route, provides
coherence.

Do not organize either form around the repository tree. Source files enter only
when they prove a mechanism or let the reader continue the investigation.

### Dependency-safe narration

Do not convert dependencies into a mandatory topological outline. The prose may
preview an effect before its cause, introduce a question before its vocabulary,
or delay an explanation for useful suspense.

Require only this: explain an idea sufficiently before asking the reader to use
it. Use these preferences when they help:

- visible behavior before abstract architecture;
- required distinctions before relations that depend on them;
- ownership and fact sources before consistency, recovery, or cleanup
  mechanisms;
- ordinary language responsibilities before current implementation names;
- a complete normal path before detailed exceptions that depend on it;
- each material claim close to the evidence that supports it.

Move a claim away from immediate evidence when the separation creates a useful
question and the evidence returns before trust is required. Do not require one
section per dependency node or preserve a prior chapter's section count.
Generate headings from the actual transition the reader is making.

### First-principles derivation

First principles means testing a plausible solution's assumptions against the
system's real ownership and failure boundaries. It does not mean opening with
universal abstractions.

For the central naive solution:

1. Show why a reasonable engineer would try it.
2. State the assumptions required for it to work.
3. Test those assumptions against state ownership, commit boundaries, resource
   lifetime, and external effects.
4. Keep the useful part of the idea and replace the invalid guarantee.

Do not confuse a carrier with the architectural assumption. JSON, JSONL,
SQLite, Redis, a registry, or a queue may be implementation choices; changing
the carrier does not repair an invalid ownership or transaction model.

### Contract and guarantee priorities

Before asking the reader to judge project mechanisms, establish the subsystem
contract somewhere in the narrative:

- what enters the subsystem;
- which state and resources it owns;
- what it guarantees;
- what it explicitly does not guarantee;
- how it represents unknown or partial outcomes.

A list of guarantees is incomplete when two guarantees cannot always be kept
at once. State the project's local priority rule, then show a real case where
the lower-priority property yields. For example, a system may prefer an
explicit failure over guessing a repair, but do not copy this example unless
the project source and behavior support it.

When an industry section is useful, compare every implementation with the same
questions and finish by extracting stable responsibilities or design
coordinates. The project section should then explain its position in that
space, not repeat the products one by one.

### Stable project architecture

When the reader needs a transferable model, name a small set of
responsibilities that explains the project's solution without depending on its
current repository layout. A good architecture model survives these edits:

- a class is renamed or split;
- a file moves;
- one storage carrier is replaced by another;
- an adapter changes while ownership and guarantees remain.

Use the smallest set of responsibilities that explains the subsystem's
ownership, invariants, and failure policy. Let current files and types reveal,
challenge, or prove that model according to the narrative movement. Do not
target a count or merely translate directory names into boxes.

### Mechanism-level reasoning

Use this as a reasoning checklist, not a visible template for every subsection:

```text
failure
-> why the naive approach fails
-> invariant
-> chosen mechanism
-> gain
-> cost
-> remaining non-guarantee
-> source, test, or experiment evidence
```

Vary the prose and headings according to the mechanism. A reader should feel a
causal argument, not see the same eight labels repeated throughout the chapter.

### Evidence closure

Separate four evidence levels:

| Level | Safe claim |
| --- | --- |
| Current implementation | Current source and matching tests support the behavior |
| Implementation boundary | Types or call order support an inference, but no independent fault test proves it |
| Experiment observation | A commit-bound workload and environment produced the result |
| Future capability | A proposal or design direction, not current product behavior |

Map verification back to the guarantees wherever the narrative can carry it.
A closing verification section is optional. Each fault experiment should prove
one boundary; a test count is never a substitute for explaining what those
tests exercise.

## Reader review

An adversarial reader should report only passage-level evidence:

- where the semantic center disappears rather than temporarily recedes;
- where more than a few unexplained terms arrive together;
- where the reader is asked to use an idea that has only been previewed;
- where a detour does not return with new understanding;
- where a diagram appears before its question or lacks a takeaway;
- where a code block exposes many fields without saying what to read;
- where an early failure creates a useful question, and where it instead depends
  on a normal model the reader does not yet have.

Cap each report at five high-impact findings. Revise until no high-impact
structural blocker remains; do not continue merely to vary harmless wording.

## Verification checklist

Hard gates:

- The private chapter contract names a real reader baseline and a checkable
  target capability.
- Source anchors exist on current source truth and support the claims made from
  them.
- Every major guarantee maps to evidence, and untested boundaries remain
  labeled as inferences, observations, or proposals.
- No behavior, number, experience, external mechanism, or proof is invented.
- The finished chapter stays inside the user's requested scope and gives the
  reader the promised capability.
- Code fences, links, image files, and published-document structure are valid.

Post-draft review questions:

- Does a verifiable thesis, tension, or recurring question provide semantic
  gravity without forcing every section into one claim?
- Are cognitive dependencies safe even when the prose foreshadows, delays, or
  loops back?
- Does a concrete task, result, failure, image, or other opening give this
  reader enough traction?
- Does the source path arrive when the reader has a reason to use it?
- Does each early exception create a useful question, or does it require a
  normal model the reader lacks?
- Are ownership, fact sources, contracts, and guarantee priorities available
  before the reader must reason from them?
- Do stable responsibilities survive removal of current class, file, and
  carrier names when transfer is part of the target capability?
- Can the learning model decide one nearby scenario not explicitly walked
  through in the chapter?
- Does substantial material contribute cognition, orientation, memory, rhythm,
  voice, or evidence without displacing something more important?
- Do repeated headings, callouts, section counts, and cadence across neighboring
  chapters have a topic-specific reason?
- Does the ending resolve or deliberately leave open the semantic center rather
  than append a generic summary?

Do not fail a draft merely because it breaks a teaching default. Change it only
when the alternative would improve the reader outcome or a hard gate.
