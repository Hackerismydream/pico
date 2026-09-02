<!--
Snapshot source: project-tutorial-writer/references/domain-model-driven-writing.md
Snapshot date: 2026-09-02T09:38:10.075Z
Purpose: make the Pico tutorial-writing guidance readable from GitHub.
-->
# Domain-model-driven tutorial design

Use this method to preserve a chapter's semantic center while leaving its
narrative form open. It constrains truth, evidence, and reader outcomes more
strongly than sequence, pacing, voice, or surface structure.

## Contents

- [Operational model](#operational-model)
- [Separate hard constraints from expressive freedom](#separate-hard-constraints-from-expressive-freedom)
- [Build the chapter contract](#build-the-chapter-contract)
- [Build the domain model](#build-the-domain-model)
- [Establish the semantic center](#establish-the-semantic-center)
- [Build the cognitive dependency map](#build-the-cognitive-dependency-map)
- [Route the narrative without fixing its form](#route-the-narrative-without-fixing-its-form)
- [Let materials earn their place](#let-materials-earn-their-place)
- [Compose a dependency-safe narrative](#compose-a-dependency-safe-narrative)
- [Run transfer, coherence, and anti-template gates](#run-transfer-coherence-and-anti-template-gates)
- [Recognize failed structures](#recognize-failed-structures)
- [Use AI as a modeling collaborator](#use-ai-as-a-modeling-collaborator)

## Operational model

Treat a tutorial as a controlled change in what the reader can explain,
predict, debug, or decide:

```text
reader state A + domain model D + evidence E
-> semantic center C + cognitive dependencies G
-> one of many valid narrative structures S
-> target capability B
```

- **A** records what the reader already knows and where their current model
  breaks.
- **D** describes the smallest stable set of objects, owners, lifecycles,
  relations, and invariants needed for this topic.
- **E** bounds what the source, tests, experiments, and external references can
  honestly support.
- **C** is the proposition, tension, or recurring question that gives the
  chapter semantic gravity.
- **G** records what the reader must understand before being asked to use it.
- **S** is one possible composition, not the graph made visible as an outline.
- **B** is an observable ability, not a promise that the reader will merely
  "understand" the topic.

A template fixes `S` before `A`, `D`, `E`, `C`, and `G` are known. An
over-constrained method also fails when it allows only one `S` after they are
known. Preserve a family of valid forms and choose through writing, not merely
through outline optimization.

Keep the modeling artifacts private and lightweight unless the user asks to
inspect the reasoning.

## Separate hard constraints from expressive freedom

Apply different freedom levels to different variables:

| Layer | Freedom | Rule |
| --- | --- | --- |
| Current facts, source identity, and evidence scope | Low | Do not improvise |
| User scope and target capability `B` | Low | Do not silently change the assignment |
| Domain distinctions and cognitive dependencies | Medium | Preserve what later reasoning requires, but choose how to reveal it |
| Narrative movement, headings, pacing, voice, analogy, and local detours | High | Let the chapter find its own form |

Treat ordering and style advice as defaults. A default may be broken when the
alternative better serves `B` without weakening facts, evidence, or scope.
Do not make the prose visibly demonstrate compliance with the method.

## Build the chapter contract

Write a compact internal contract before choosing headings:

| Field | Operational question |
| --- | --- |
| Reader baseline | What can the intended reader already trace, explain, or operate without this chapter? |
| Target capability | What new explanation, prediction, debugging path, or design decision should they reproduce afterwards? |
| Visible problem | Which concrete task, result, surprise, or failure makes that capability necessary? |
| Scope | Which boundary must the chapter cross, and which adjacent subjects can remain outside? |
| Current facts | Which behavior is true in the inspected source or artifact? |
| Evidence boundary | Which claims are proven, inferred, observed, externally sourced, or still proposed? |

Express the target capability with a verb and a checkable situation. Prefer
"decide whether this retry can duplicate an effect" over "understand retries."

Do not substitute a reader biography, a list of learning objectives, or an
inventory of repository modules for this contract.

## Build the domain model

Model the domain before modeling the repository. Include only distinctions
that change the explanation or a reader decision.

### Identify the irreducible pieces

Ask:

- What objects or events cannot be merged without making a later claim false?
- Who owns each mutable state, resource, external effect, and authoritative
  fact?
- When is each object created, committed, observed, invalidated, and closed?
- Which relations are causal, prerequisite, capacity, containment, projection,
  or ownership relations?
- Which invariant must remain true across the relevant failures?
- Which things is a beginner most likely to collapse into one concept?

Keep these distinctions explicit:

| Distinction | Test |
| --- | --- |
| Domain object vs implementation type | Would the idea survive a class rename or split? |
| Owner vs caller | Who controls the state or lifetime, not merely who invokes a method? |
| Fact source vs copy | Which representation settles a disagreement? |
| Lifecycle vs execution sequence | Does the object outlive one request or process? |
| Invariant vs common behavior | Must it remain true, or does it merely happen on the happy path? |
| Responsibility vs carrier | Would replacing JSONL, SQLite, a queue, or a registry leave the architectural need intact? |

### Reduce the model

1. Collect candidate nouns, state transitions, and failure boundaries from the
   scenario, source, and tests.
2. Merge synonyms that have the same owner and lifecycle.
3. Split overloaded terms when they hide different owners, truth sources, or
   commit boundaries.
4. Attach each remaining object to its owner, lifecycle, relations, invariant,
   and evidence.
5. Remove project names and implementation carriers, then explain one nearby
   case with the remaining model.

If the reduced model cannot predict anything beyond the example used to build
it, it is a glossary, not a learning model. Inspect more source or choose a
narrower target capability.

Do not create ontology tables merely to appear rigorous. Use prose, bullets, a
small relationship map, or a state diagram according to the actual problem.

## Establish the semantic center

The semantic center is what makes a locally varied chapter still feel like one
piece. It may be:

- one verifiable thesis that makes later choices unsurprising;
- a tension between guarantees that cannot all be maximized;
- a recurring engineering question whose answer changes as evidence arrives;
- a small, connected cluster of claims that cannot honestly be reduced to one
  sentence.

Accept a semantic center when it:

- resolves the reader's central misconception or missing relation;
- gives detours and examples something meaningful to return to;
- can be challenged by source, a counterexample, or an experiment;
- remains meaningful after product and implementation names disappear;
- stays narrow enough for the chapter's evidence to support.

Reject topic labels, universal slogans, and forced single-cause explanations:

```text
Weak: This chapter explains the recovery system.
Weak: Reliability comes from layered design.

Useful: Recovery crosses several independently owned state domains, so no
single transcript can promise to restore every effect or execution state.
```

The useful version creates consequences without dictating section order. It
implies that the reader eventually needs to distinguish owners, understand the
recovery contract, see how uncertain state is represented, and know what the
evidence proves. The prose may reveal those needs through a failure, an image,
a question, or a return to an earlier scene.

## Build the cognitive dependency map

A node is a change in the reader's mental model, not a section title, source
fact, or file name. An edge means the reader must understand one idea before
they are asked to use another idea in an explanation or decision.

An edge does not ban earlier mention. The prose may preview a term, show an
unexplained result, plant a question, or return to an image later. Dependency
safety governs use, not first appearance.

Build the graph backwards from the target capability:

1. State the final judgment or explanation the reader must make.
2. Ask what distinctions, relations, or causal claims must already be true for
   that judgment to make sense.
3. Continue until the remaining prerequisites are already in reader state `A`
   or can be grounded directly in visible behavior.
4. Attach evidence to the claims it supports. Do not create a detached evidence
   appendix unless the user needs an audit artifact.
5. Remove orphan facts and branches that do not help reach `B`.
6. Merge repeated claims that differ only in project vocabulary.

For example, a reader cannot judge whether a historical action is safe to
continue until they distinguish a recorded fact from a replay instruction,
identify who owns the external effect, and know what evidence exists after a
crash. Those are prerequisite claims. The archive type and function names are
supporting evidence, not the graph's organizing nodes.

Sections come later. One section may group several connected nodes; one node
may unfold across the chapter. Never force one node into one heading or expose
the map as a visible sequence merely for symmetry.

## Route the narrative without fixing its form

Use the semantic center as gravity, not as a railway track. Choose a dominant
movement only when it helps. A chapter may braid a request, a failure, a
conceptual distinction, or an ownership question when the movements illuminate
one another and return to the same center.

| Reader obstacle or graph shape | Useful narrative device |
| --- | --- |
| Data crosses several owners before a visible result | Request path or timeline |
| Two adjacent concepts are being collapsed | Boundary map, contrast, or counterexample |
| A plausible naive solution hides invalid assumptions | Construct the solution, then test its assumptions against failures |
| Several systems own related state | Ownership and lifecycle map |
| Guarantees cannot all be preserved | Conflict scenario followed by an explicit priority decision |
| Competing implementations expose a real design choice | Shared-question industry comparison followed by design coordinates |
| A reliability promise needs proof | Fault experiment paired with the exact claim it challenges |
| The model is clear but source navigation is not | Small request-ordered code compass |
| The reader needs to perform an operation | Complete happy path with visible completion and bounded failure branches |

Do not add an industry survey because the topic sounds architectural. Do not
add a lifecycle table when only one owner matters. Do not turn every failure
into its own section when several failures test the same invariant.

A request path and a design derivation can coexist. A design argument may
contain one complete happy path; a request path may open with a later failure
and return to it. Do not combine complete preset outlines or keep a branch that
never changes the reader's understanding of the center.

## Let materials earn their place

Treat material selection as part of the reading experience:

| Material | Valid narrative job |
| --- | --- |
| Scenario or failure | Expose a gap, create orientation, or give an abstract issue human scale |
| Analogy | Lower the cost of a relation, make it memorable, or change the rhythm before returning to the limit |
| Industry implementation | Reveal a design space or a competing guarantee choice |
| Project source | Prove how the project instantiates a previously explained responsibility |
| Test or fault experiment | Challenge one claim at its real boundary |
| Number or measurement | Support a scoped observation with workload and environment context |
| Diagram | Make ownership, sequence, state change, or branching easier to inspect than prose |
| Code compass | Let the reader continue investigation in request order |
| Transition or breathing paragraph | Reset cognitive load, change pace, or prepare a return without adding a new claim |

Substantial material should contribute to cognition, orientation, memory,
rhythm, voice, or evidence. Do not require every paragraph to advance a formal
claim. Remove material only when it contributes to none of these, distracts
from the semantic center, or consumes attention that a later dependency needs.

A technically correct source excerpt can still weaken the chapter when the
reader has no question for it. A short scene or pause can strengthen the
chapter even when it proves nothing directly.

## Compose a dependency-safe narrative

Do not convert the dependency map directly into a topological outline. A good
chapter can introduce an effect before its cause, show a failure before the
normal path, suspend a term, or revisit the same scene after the reader's model
changes.

Preserve one boundary: explain an idea sufficiently before asking the reader to
use it. A preview creates curiosity; premature use creates confusion.

Use these as defeasible defaults:

- Establish a visible problem or result early when it gives the reader useful
  traction.
- Introduce distinctions before asking the reader to reason from them.
- Establish ownership and fact sources before asking the reader to judge
  consistency, recovery, cancellation, or cleanup mechanisms.
- Explain responsibilities in ordinary language before current implementation
  names when the names would otherwise become a barrier.
- Complete the normal operation before detailed exceptions when those
  exceptions depend on the normal model; lead with a failure when it creates
  the real question.
- Keep a claim close to its evidence when proximity improves trust; delay the
  evidence when immediate proof would destroy a useful narrative movement.
- End after the reader can exercise capability `B`; do not append a generic
  recap merely because prior chapters contain one.

Break a default when the alternative improves the reader's path without
weakening facts, evidence, or scope. If the form is uncertain, draft rather
than endlessly optimize outlines. Compare alternatives only when a structural
choice remains genuinely ambiguous.

Judge a draft by asking:

- Does it introduce only as many unsupported terms as the current movement can
  carry?
- Does it keep a meaningful question alive long enough to resolve it?
- Does evidence answer existing questions instead of creating a
  fact dump?
- Does the final judgment become possible without flattening every detour?
- Does the shape differ from neighboring chapters for a real cognitive or
  expressive reason?

Generate headings from the actual transition or engineering question. Avoid
generic recurring slots such as "background," "core concepts," "implementation
details," and "summary" unless those words precisely describe the chapter's
argument.

## Run transfer, coherence, and anti-template gates

Run these gates after the complete draft exists:

| Gate | Pass condition | Failed-gate action |
| --- | --- | --- |
| Name removal | The explanation still works without product, class, file, and carrier names | Rebuild the domain model around responsibilities and relations |
| Unseen scenario | The intended reader can use the model to decide one nearby case not walked through in the draft | Strengthen the semantic center, invariant, or decision rule |
| Contribution | Every substantial section contributes cognition, orientation, memory, rhythm, voice, or evidence without displacing something more important | Remove, shorten, move, or reconnect only the material that contributes nothing |
| Dependency safety | The reader may meet an unresolved idea early but is not asked to use it before explanation | Repair the point of premature use; preserve useful foreshadowing |
| Evidence scope | Each strong claim stays inside what its source, test, or experiment proves | Narrow the claim or add appropriate evidence |
| Material role | Analogies, comparisons, diagrams, code blocks, and numbers help the reader or the prose enough to justify their attention cost | Delete, move, or replace material that is merely present |
| Cross-article isomorphism | Repeated headings, section counts, callouts, and rhythms have a topic-specific reason | Return to this chapter's center instead of normalizing its surface |
| Reader ability | A reader can explain, predict, debug, or decide the contracted outcome | Repair the missing cognitive step rather than polishing sentences |

Run factual, reader, and template reviews separately. A clean factual review
does not prove the learning path works. A pleasant reader review does not prove
the claims are current. A varied surface does not prove the underlying
structure was derived rather than copied. Conversely, do not make a strong
draft more regular merely to satisfy a heuristic visibly.

## Recognize failed structures

| Failure mode | Diagnostic sign | Repair |
| --- | --- | --- |
| Module tour | Chapter order mirrors directories or class definitions | Rebuild nodes from reader decisions and runtime relations |
| Hanging hook | Opening story never affects the later explanation | Connect it to the semantic center or remove it |
| Terminology first | Several names arrive before any visible action or distinction | Start from behavior and introduce names at first use |
| Boundary-led audit | Caveats and exceptions crowd out the normal model | Establish the main path, then place boundaries beside affected claims |
| Product catalog | Each external tool gets an isolated feature summary | Compare all implementations through the same decision questions |
| Evidence dump | Tests and source excerpts appear without nearby claims | Attach each artifact to the promise it supports |
| Numeric quota | The writer targets a fixed number of files, sections, diagrams, or responsibilities | Let cognitive needs and expressive judgment determine selection |
| First-principles slogan | Abstract principles appear without a plausible solution being tested | Expose assumptions and test them against ownership and failure boundaries |
| 范文复刻 | A prior article's headings survive after the subject changes | Return to `A`, `B`, `C`, `D`, `E`, and `G` before composing a new form |
| Topological literalism | Every prerequisite becomes an earlier section, leaving no suspense or return | Preserve dependency safety while allowing previews and delayed explanation |
| Checklist prose | Each paragraph visibly performs one method step or closes with a lesson | Draft without the checklist and review only after the whole piece exists |
| Utilitarian pruning | Scenes, pauses, and voice disappear because they prove no claim | Judge their contribution to orientation, memory, rhythm, and attention |
| Over-closure | Every branch resolves immediately and the prose never breathes | Let a real question stay open until the reader has enough material to answer it |

## Use AI as a modeling collaborator

Do not ask an agent to write the final chapter directly from a repository dump.
Use distinct internal passes:

1. Recover current source truth and evidence boundaries.
2. Derive the chapter contract, domain model, semantic center, dependencies,
   and evidence map in compact working notes.
3. Write one complete draft while actively enforcing only the hard constraints.
   Allow the prose to discover its movement.
4. Review facts, reader progression, semantic coherence, and template leakage
   in separate passes.
5. Revise the model or dependency safety before polishing sentences when a
   structural gate fails.
6. Stop when remaining changes would merely make the chapter more uniform,
   explicit, or compliant-looking.

Keep the working representation flexible. A tiny chapter may need a few
bullets; a multi-owner architecture chapter may need a relationship graph and
an evidence map. Requiring the same planning artifact for every chapter would
recreate the template problem inside the authoring process.
