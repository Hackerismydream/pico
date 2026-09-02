<!--
Snapshot source: project-tutorial-writer/references/ai-style-review.md
Snapshot date: 2026-09-02T09:39:09.880Z
Purpose: make the Pico tutorial-writing guidance readable from GitHub.
-->

# Post-draft AI-style review

Read this only after a complete draft exists and either the user asks to reduce
AI-like prose or the draft shows mechanical uniformity. Diagnose comprehension
and voice problems; do not rewrite merely to disguise origin or make every
chapter casually different.

## Contents

- [High-value fingerprints](#high-value-fingerprints)
- [Negation as the only rhetorical engine](#negation-as-the-only-rhetorical-engine)
- [Meta-discourse layer](#meta-discourse-layer)
- [Template uniformity](#template-uniformity)
- [Word-hammer repetition](#word-hammer-repetition)
- [Interview-bait framing](#interview-bait-framing)
- [Review boundary](#review-boundary)

## High-value fingerprints

Ask `$dbs-ai-check` to scan all fingerprints, then prioritize these tutorial
failures:

| Fingerprint | Tutorial symptom | Preferred action |
| --- | --- | --- |
| #2 knowledge output | Objects, enums, branches, and numbers arrive before a usable example | Keep what the current movement can carry; move the rest later |
| #3 uniform parallelism | Consecutive sections use identical list shapes | Let the mechanism determine paragraph shape |
| #8 defensive flips | Repeated `不是 X，而是 Y` definitions | State ownership and behavior directly |
| #13 constant punchlines | Every section ends with `记住一句话` or a polished slogan | Keep only conclusions that change the reader's model |
| #14 uniform rhythm | Paragraphs and sentences have nearly identical length | Preserve natural short transitions, pauses, and longer explanations |
| #17 connective overuse | `首先/其次/最后/然而/值得注意的是` carry the structure | Let subjects and actions show the transition |
| #19 translationese | Heavy `基于/关于/作为/进行` phrasing | Write how an engineer would explain it aloud |
| #22 artificial depth | A practical mechanism is inflated into a universal principle | Return to the concrete failure or trade-off |

Do not mechanically act on every match. Technical writing legitimately
contains definitions, exhaustive contracts, and repeated canonical terms.

## Negation as the only rhetorical engine

Symptom: `不是 A，而是 B` plus `不代表 / 不等于 / 不应该 / 不要` become the
chapter's dominant argumentative device. Every claim erects a target before
knocking it down.

Why it feels mechanical: the prose defends itself from every possible
misreading instead of letting behavior and ownership carry the explanation.

Fix: keep negations that perform real contrast work. State what something does
first, and place the contrast where the distinction becomes consequential.

```text
❌ "provider-safe"不是安全审查。它只表示删除 timestamp、内部 id……
✅ "provider-safe"投影删除 timestamp、内部 id、manifest 标注等运行时私有字段，
   保留 role、content、tool_calls、tool_call_id、name 和 reasoning 字段。
   它和内容安全审查无关。
```

## Meta-discourse layer

Symptom: actions are repeatedly introduced by labels such as `先记住一句话`、
`看图前先回答`、`读图提示`、`回到贯穿任务`、`名字容易混`，or the author
explains why its own paragraph is effective.

Fix: delete labels that narrate the writing process. Keep a reminder only when
it carries a real name collision, security boundary, reading cue, or task
orientation. Let the paragraph demonstrate its value.

```text
❌ 这不是在说当前 main 存在这个 Bug；它是本章的读码线索。
✅ 这个用例在当前 main 上是过的；它是本章追数据的线索，不是真实缺陷。
```

## Template uniformity

Symptom: every section has the same callout, consecutive headings use the same
self-answered question shape, or the chapter exposes a fill-in-the-blank
skeleton such as `适合谁 -> 基线 -> 读完会什么 -> 第 N 站 -> 复盘`.

Fix: keep only structures that this mechanism and reader need. Preserve useful
recurrence, but remove repeated furniture that makes the mold more visible than
the subject.

```text
❌ 为什么不能把所有材料都塞进去      ✅ 不能全塞的两个原因
❌ 为什么它只是第一层估算          ✅ 这是第一层估算
❌ 为什么五个 Builder 可以并行      ✅ 五个 Builder 能并行的条件
```

## Word-hammer repetition

Symptom: a thematic word becomes conspicuously repetitive, or the same boundary
is restated in a definition, table, section, callout, and conclusion.

Fix: keep the canonical term where precision requires it. Elsewhere use natural
references or drop the repetition. Repeat a boundary when its engineering
consequence changes, not because the writer fears it was missed.

## Interview-bait framing

Symptom: the chapter aims to impress a hypothetical interviewer, so paragraphs
hedge, summarize themselves, and turn mechanisms into polished sample answers.
Numbers lack environment or sampling context.

Fix: return to one concrete engineering question. Use first-person or direct
explanation when natural, vary sentence length, ground numbers in their
workload, and remove defenses against imagined criticism.

```text
❌ 在 Pico 中，一次 Agent 迭代前，Context Engine 会把身份和项目规则、召回的
   Memory、匹配的 Skills、Session 历史、当前请求与工具 schema 组合成 Provider
   请求。因此上下文工程的核心不是一个 Prompt，而是……
✅ 模型要修一个失败的测试，这一轮该让它看到什么？Pico 的 Context Engine 会把
   身份和项目规则、召回的 Memory、匹配的技能、会话历史、当前请求和工具 schema
   组装成 Provider 真正收到的 messages 和 tools。上下文工程拼的不是 prompt，
   是这一轮给模型看什么、暂时不看什么。
```

## Review boundary

Preserve deliberate asymmetry, suspense, breathing room, recurring images, and
authorial voice. Change a passage only when it blocks comprehension, weakens
the semantic center, creates unsupported certainty, or makes the underlying
template more visible than the subject.

Stop when remaining suggestions are matters of taste or would merely make the
chapter more regular.
