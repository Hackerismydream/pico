# PicoBench v0.4 Plan

PicoBench v0.4 should move beyond v0.3 RC smoke coverage into auditable
dogfood, true resume/subagent coverage, and real ablation controls. This is a
plan only; no v0.4 implementation is included in the v0.3 RC branch.

## Goals

1. Add 5-10 true dogfood-derived tasks. Every task must include
   `metadata.source_commit` or a reference patch id, plus a short provenance
   note.
2. Implement a true two-pass resume benchmark:
   first run creates checkpoint/task state, second run uses `--resume latest`,
   and verifiers check session continuity, task-state continuity, checkpoint id,
   changed paths, evidence consistency, and actual resume command usage.
3. Implement a true subagent benchmark using runtime trace/session events:
   `subagent_started`, `subagent_completed`, `subagent_mode=explore`,
   read-only scope evidence, and no business file changes.
4. Add public runtime feature flags so real ablation can run through the same
   public CLI boundary:
   - `--disable-memory`
   - `--disable-plan-mode`
   - `--disable-subagents`
   - `--disable-skills`
5. Run at least one multi-provider live comparison after the benchmark surface
   and evidence contracts are stable.

## Non-Goals For v0.3 RC

- Do not add v0.4 tasks to v0.3.
- Do not implement resume/subagent runtime support during RC freeze.
- Do not fabricate ablation results before feature flags exist.
- Do not describe v0.3 as a public leaderboard.
