---
id: picobench-005
scope: evaluation
status: completed
depends-on:
  - picobench-002
authority-issue: 59
gates: [G3, G4, G5]
requires-live-provider: false
---

# PicoBench Memory and Skill Task Pack

This completed task card records the historical pre-CodeCairn Memory/Skill
experiment identity.

## Objective

Measure user Memory recall and Skill-source fusion as two independent
mechanisms, then test whether each helps a later Session complete a task.

## Context

User Memory uses EverOS user-track recall. SkillForge combines Local BM25 and
EverOS agent-track semantic retrieval through weighted RRF. Passing
`backend=None` changes both paths and is not a valid Memory-only baseline.

Owned paths:

```text
benchmarks/picobench/packs/memory_skill/
benchmarks/picobench/tasks/memory_skill/
benchmarks/picobench/fixtures/retrieval/
tests/test_picobench_memory_skill_track.py
tests/integration/test_picobench_memory_skill_e2e.py
```

## Path

1. Freeze separate `user_memory_retrieval` and `skill_source_fusion` corpora and
   schemas. Each owns its query labels, ranking semantics, metrics, and Claim
   Rules.
2. Freeze the user-Memory suite at exactly 160 facts, 50 positive queries, 30
   hard negatives, and one enabled configuration: 80 Retrieval Cases.
3. Freeze the Skill suite at exactly 40 positive queries, 20 hard negatives,
   and three configurations (`local_only`, `everos_only`, `fused`): 180
   Retrieval Cases. Cover Local BM25, EverOS semantic, weighted RRF, source
   overlap, and cross-workspace distractors.
4. Record hashed item id, source, rank, raw score, RRF score when applicable,
   contributing sources, injection decision, query id, and consuming Turn
   without storing recalled content in the aggregate report.
5. Report backend retrieval and final Context injection separately using the
   metric namespaces fixed by the contract.
6. Persist all 260 Retrieval Cases and their query-block attempts under the
   canonical artifact layout. Rerun every configuration in a contaminated
   query block together, at most once.
7. Freeze eight two-Session tasks with Runtime teardown and a fresh evaluation
   process between learning and reuse.
8. Run three arms: user-Memory-off with Local-plus-EverOS Skills;
   user-Memory-on with Local-only Skills; and user-Memory-on with
   Local-plus-EverOS Skills.
9. Run all three arms in one Comparison Block attempt. Derive the Memory Pair
   from arms one and three, and the Skill Pair from arms two and three. Reject
   any other variant difference.
10. Keep the same `MemorySegmentBuilder`, host `user.md` rendering, Curator
   Memory configuration, backend, and Skill sources in the Memory Pair. The
   baseline suppresses only delegated user-track recall and records the
   suppressed-call count.
11. Treat learning, backend quiescence, Runtime teardown, and fresh-process
    evaluation as phases of one Trial, and account for all required usage.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_memory_skill_track.py -q
uv run pytest tests/integration/test_picobench_memory_skill_e2e.py -q
```

Acceptance:

- user-Memory-off records zero user-track recall calls while the declared Skill
  sources remain available;
- the Memory Pair has identical host-Memory rendering and Curator configuration
  digests;
- every Trial has isolated EverOS, Session, and workspace state;
- stale injection and cross-workspace leakage are zero;
- user Memory and Skill fusion evaluate separate named retrieval Gates;
- all 260 planned Retrieval Cases have terminal, rebuildable records; positive
  retrieval claims require 100 percent measurable coverage;
- user-Memory positive eligibility uses
  `memory.final_injection_recall_at_5 >= 0.80` and
  `memory.hard_negative_injection_rate <= 0.05`;
- Memory and Skill task-result eligibility are computed separately, each
  requiring at least two net gains across 24 repetition Pairs, at least two
  positively affected tasks, and no task losing two of three passes;
- weighted RRF is attributed to SkillForge, not to user Memory recall.
- a weighted-RRF improvement claim requires fused Recall@5 to exceed the best
  single source by at least 0.05, hard-negative injection at most 0.05, and
  cross-workspace leakage zero.
