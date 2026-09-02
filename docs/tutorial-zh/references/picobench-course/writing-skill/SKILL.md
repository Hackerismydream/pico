<!--
Snapshot source: project-tutorial-writer/SKILL.md
Snapshot date: 2026-09-02T09:38:09.982Z
Purpose: make the Pico tutorial-writing guidance readable from GitHub.
Adaptation: local-only industry-source instructions are replaced by public-source guidance.
-->
---
name: project-tutorial-writer
description: Write or rewrite source-driven software project tutorials that keep facts, evidence boundaries, and reader outcomes strict while allowing flexible narrative shape, pacing, voice, and local detours. Use for project-learning docs, code-reading guides, design-decision chapters, architecture comparisons, onboarding manuals, or Markdown/Feishu course pages when the user asks to explain runtime behavior from first principles, clarify guarantees and trade-offs, compare implementations through shared design questions, turn a source tour into a transferable learning model, preserve a semantic center without imposing a template, reduce AI-like prose, or place technical diagrams inside the narrative.
---

# Project Tutorial Writer

Produce a finished tutorial chapter in one compact workflow:

```text
read current source truth -> set the hard contract for A, B, facts, and evidence
-> derive domain model D, semantic center C, dependencies G, and evidence E
-> write one complete draft with high narrative freedom
-> review factual integrity, reader ability, semantic coherence, and template leakage
-> verify
```

Do not expose planning machinery unless the user asks for it. Deliver the rewritten chapter, verification result, and links.

## Required references

Read [references/writing-rules.md](references/writing-rules.md) for every task.

Read [references/domain-model-driven-writing.md](references/domain-model-driven-writing.md) when designing a new chapter, substantially reorganizing one, or fixing a draft whose structure follows source files, a prior chapter, or a generic tutorial skeleton. It defines asymmetric constraints, the semantic center, cognitive dependencies, flexible narrative movement, material roles, and transfer tests.

Read [references/industry-sources.md](references/industry-sources.md) before writing any chapter that has an industry-reference section. It explains how to use public primary sources without inventing third-party behavior.

Read [references/ai-style-review.md](references/ai-style-review.md) only after a
complete draft exists and either the user requests lower AI flavor or the draft
shows mechanical uniformity. Do not load its checklist during first-draft
generation.

Read [references/gold-examples.md](references/gold-examples.md) only when the
user asks to calibrate against the existing course, when resolving a genuine
style conflict, or when reviewing cross-chapter consistency. Do not load prior
chapter shapes by default while inventing a new chapter; examples can bias the
form before this chapter finds its own movement.

## Default workflow

### 1. Read current source truth

- Fetch and inspect the repository's latest `origin/main` when network access is available. Otherwise state that the local `origin/main` may be stale.
- Capture the inspected commit internally for traceability; do not turn SHA management into a user-facing workflow.
- Read the primary implementation path and matching tests before changing technical claims.
- Preserve unrelated working-tree changes. Prefer a clean read-only checkout or worktree for source inspection.
- For a documentation-only request, report a discovered source bug instead of silently changing code. Fix source only when the user's scope authorizes it.

### 2. Set asymmetric constraints

Keep freedom low for facts and high for expression.

Hard constraints:

- Stay inside the user's scope and the intended reader's target capability.
- Keep every technical claim inside current source or explicitly identified
  evidence.
- Never invent behavior, numbers, personal experience, external mechanisms, or
  proof.
- Leave the reader able to perform the promised explanation, prediction,
  debugging task, or design judgment.

Everything else in this Skill is a defeasible teaching heuristic unless the
user makes it an explicit requirement. Break a default when the alternative
better serves the target capability without weakening truth, evidence, or
scope. Do not make compliance with the Skill visible in the prose.

### 3. Derive the semantic spine before choosing its form

Use `$dbs-deconstruct` when available, but apply only its lightweight concept-reduction method. Do not generate seven ontology tables.

Define the reader state before the outline:

- What can this reader already do without the chapter?
- What concrete explanation, debugging task, design judgment, or source path
  should they be able to reproduce afterwards?

Create these private working notes before choosing headings:

- **Chapter contract**: reader baseline, target capability, visible problem,
  scope, current facts, and evidence boundary.
- **Domain model**: irreducible objects, owners, lifecycles, fact sources,
  relationships, invariants, and likely confusions.
- **Semantic center**: a verifiable thesis, connected tension, recurring
  question, or coherent cluster of claims that gives the chapter gravity
  without forcing every section into one sentence.
- **Cognitive dependency map**: what the reader must understand before they are
  asked to use it. A concept may be previewed before it is fully explained.
- **Evidence map**: the source, test, experiment, or external evidence that
  supports each material claim.

Keep these notes in working context only. Use compact bullets or a small graph;
do not create separate planning files, expose them in the answer, or turn
chapter planning into a second deliverable unless the user explicitly asks.

Accept the learning model only when it still explains the mechanism after
current project, class, file, and storage-carrier names are removed, and when
it can predict at least one relevant scenario not used in the chapter.

If the mechanism cannot be explained in plain language, inspect more source
before writing.

Identify the chapter's center of gravity after the model exists. A dominant
movement may help, but it is not mandatory:

- Use a **request path** when the explanation mainly follows data and ownership
  across a completed operation.
- Use a **design derivation** when the explanation mainly follows a failure,
  hidden assumptions, ownership boundaries, competing guarantees, and the
  mechanisms chosen in response.

Treat these as possible movements, not exhaustive output forms. A chapter may
braid movements, foreshadow a later explanation, or leave the main line briefly
when the detour returns with new understanding. Do not stack complete tutorial
skeletons or let a branch replace the semantic center.

### 4. Write one free but coherent draft

- Write the whole first draft while actively enforcing only the hard
  constraints. Do not stop each paragraph to satisfy the review checklist.
- Allow foreshadowing, delayed explanation, local detours, uneven pacing,
  contrast, recurrence, and changes in paragraph length. The prose may wander
  locally as long as it returns to the semantic center with new understanding.
- Treat a dependency as broken only when the reader is asked to use an idea
  before it is sufficiently explained. Mentioning it earlier as a question,
  image, mystery, or promise is allowed.
- Let substantial material earn its place through cognition, orientation,
  memory, rhythm, voice, or evidence. Do not require every paragraph to advance
  a formal claim.

Use these as defaults, not mandatory order:

- Start from a concrete task, result, or failure when it gives the reader useful
  traction.
- Explain behavior in ordinary language before a code name when the name would
  otherwise become a comprehension barrier.
- Complete the normal path before detailed exceptions when the exceptions rely
  on that path; lead with a failure when the failure creates the real question.
- Establish ownership, fact sources, or the subsystem contract before asking
  the reader to judge mechanisms that depend on them.
- Place a small code compass after the reader has a reason to navigate the
  source. Order it by the investigation rather than repository layout.
- Keep evidence near its claim when that strengthens trust, but move it when an
  immediate citation would break a useful narrative movement.

- Include an industry section only when real implementations reveal a useful
  design space. Research it from direct sources before writing, organize every
  harness around the same engineering questions, then extract reusable design
  coordinates. Do not describe a third-party mechanism from memory or publish
  a product-by-product feature catalog.

Use the optional teaching devices and mechanism checks in writing-rules.md only
where they help this chapter. Keep current implementation, source-order
inferences, commit-bound observations, and future proposals visibly separate.

When diagrams are required, decide their narrative jobs before generating them
and invoke `$agent-tutorial-diagrams` for raster output. Give the reader enough
context to know why to look and what relation matters, then connect the image
back to the surrounding movement. Vary the exact placement and prose; do not
turn every diagram into the same four-step block or collect several at the
opening.

### 5. Review and revise after the complete draft

Review in separate passes. Do not flatten deliberate asymmetry, suspense,
breathing room, or voice merely because another order would be more explicit.

First run a hard factual pass for source identity, claim accuracy, evidence
scope, invented details, and user scope.

Then run a reader pass for semantic coherence and dependency safety:

- Does every detour return with something the central question can use?
- Is any concept merely previewed, or is the reader prematurely required to use
  it?
- Can the reader reach the contracted target capability?
- Does the ending resolve the chapter's semantic center rather than merely
  repeat its headings?

If the user requests lower AI flavor or the complete draft shows mechanical
uniformity, read [references/ai-style-review.md](references/ai-style-review.md)
and run `$dbs-ai-check` as diagnosis only. Focus on findings that damage
comprehension, semantic coherence, or voice. Do not rewrite merely to hide AI
origin or to make variation visible.

Run the transfer and anti-template gates in
[references/domain-model-driven-writing.md](references/domain-model-driven-writing.md):
name removal, unseen scenario, contribution, dependency safety, evidence scope,
material role, and cross-article isomorphism. Treat a failed gate as a model or
structure problem. Do not convert a soft heuristic into a failure after the
draft has already solved the reader's problem.

When Pi or another independent reader is available, request at least one adversarial pass with this boundary:

```text
Read as a beginner. Report at most five high-impact places where you lose the
semantic center, are asked to use an unexplained idea, follow a detour that
never returns, or cannot connect a diagram/code block to the nearby question.
Quote the exact passage. Do not rewrite the article and do not change technical
facts.
```

If no independent reader is available, run the same checklist locally in a separate review pass.

Merge duplicate findings. Revise until no factual, reader-blocking, or semantic
finding remains. Stop when the remaining suggestions would merely make the
chapter more regular, explicit, or similar to another chapter.

Use `$write-tw93` only when the user explicitly asks for that voice or a small passage remains stiff after the main revision. Do not apply its long-sentence or no-numbering preferences to an entire code-path tutorial.

### 6. Verify and deliver

- Recheck every changed function, class, file, enum, configuration key, number, and evidence claim against current `main` or commit-bound artifacts.
- Confirm that every major guarantee has evidence and that each test is claimed
  only for the boundary it actually exercises.
- Confirm that the final explanation lets the intended reader reason about one
  nearby scenario that the chapter did not walk through explicitly.
- Check Markdown headings, fences, local links, image files, and image order.
- When publishing to Feishu, read the document back and verify title, final section, image count, and contextual image placement.
- Report only tests and checks actually run.
- Keep historical versions, migration stories, exhaustive interview scripts, and resume copy outside the teaching narrative unless the task explicitly concerns them.

## Output contract

Return the completed artifact first. Add a compact note containing:

- source identity inspected;
- material review findings fixed;
- verification performed;
- any unresolved factual boundary.

For architecture-decision chapters, also include one short architecture
summary that a reader can accurately restate and apply to a nearby scenario
without source names or storage-carrier names.

Do not return the internal deconstruction, full AI-fingerprint report, or intermediate draft unless the user requests them.
