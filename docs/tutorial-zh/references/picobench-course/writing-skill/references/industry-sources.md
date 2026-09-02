<!--
Adapted from: project-tutorial-writer/references/industry-sources.md
Snapshot date: 2026-09-02T09:39:09.932Z
Purpose: make the Pico tutorial-writing guidance readable from GitHub.
Adaptation: machine-local and non-public source paths are intentionally omitted.
-->

# Industry sources: where to borrow from, and how to be honest about it

Use an industry-reference section when real implementations expose a design
space the reader needs before evaluating the project's choice. This file tells
you where to find real material and how to use it without fabricating or
turning the chapter into a product catalog.

## Required: research before writing the reference section

Before drafting the industry section, collect sources. Do not write it from
memory or from the model's parametric knowledge — that is how fabricated
details enter a chapter. Minimum one source per harness discussed; prefer two.

Allowed source types:

- **Blog posts** (English and Chinese): engineering blogs by harness authors,
  API providers, and practitioners.
- **微信公众号 articles**: common for Chinese ecosystems (e.g. context
  compaction, agent frameworks). Cite the article title and WeChat link if
  fetchable.
- **Papers**: arXiv, ACL, TACL (Lost in the Middle, RULER, ReAct, RAG, ...).
- **Public source repositories**: prefer the exact public commit that matches
  the behavior being discussed, and read the implementation instead of a
  secondary summary.

For every claim in the industry section, attach the source (link, article
title, or file path). If you could not verify a detail, either verify it or
drop it. Never state a third-party mechanism you have not read about or read.

## Source access in a Git-only environment

Use the current repository first. For third-party behavior, use public source
repositories at named commits, official engineering documentation, or papers.
If the environment cannot open the primary material, omit the mechanism or
label it unverified. Do not substitute model memory, inaccessible local paths,
decompiled packages, or non-public source bundles.

## Honesty rules for the industry section

- The section's job is to build a reference line (顺序与成本意识), not to
  claim the harness's features as Pico's own.
- Start from one shared failure or engineering question. Ask every harness the
  same questions: state ownership, commit boundary, context projection,
  resource lifetime, failure policy, or whichever axes fit the chapter.
- Describe enough mechanism detail to explain each choice, then synthesize
  stable responsibilities or design coordinates before entering Pico.
- A short "对 Pico 的启示" is useful only when it identifies a concrete choice
  or trade-off. Do not append the same takeaway sentence to every product by
  template.
- Never put third-party mechanism details in the Pico implementation section.
- The reference list at the end of the chapter must include every source the
  industry section draws on. Pico-only chapters may omit it.
- If deleting product names leaves no reusable design model, the section is
  still a feature list and must be reorganized.
