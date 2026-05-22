# PicoBench Phase 3 Plan

Phase 3 moves PicoBench from framework construction into controlled live
benchmark operation. The target is an auditable internal PicoBench v0.2
candidate process, not a public leaderboard.

## Phase 3A: Live Smoke

- Keep no-key CI deterministic.
- Add manual `workflow_dispatch` live smoke workflow.
- Run a minimal core task with DeepSeek.
- Save summary, evidence, redacted provider config, and run manifest.
- Record the run in the execution log.

Status on 2026-05-22: completed for the first controlled smoke set. DeepSeek
ran `core_001`, the five multi-file core tasks `core_026`-`core_030`, and the
three agentic-native tasks. Results are recorded in
`docs/evaluation/live_execution_log.md` and
`docs/evaluation/live_results_summary.md`.

## Phase 3B: 10-Task Core Subset

- Select a representative mix of bugfix, security, configuration, and
  multi-file tasks.
- Run through the public CLI boundary.
- Classify failures and identify product/runtime bugs separately from task
  quality issues.

Recommended next subset: `core_001`, `core_003`, `core_011`, `core_017`,
`core_021`, `core_026`, `core_027`, `core_028`, `core_029`, `core_030`.

## Phase 3C: Full 30-Task Core Live Run

- Run all 30 core tasks only after Phase 3A and 3B are stable.
- Preserve full evidence bundles.
- Review hidden test failures before changing any task.

## Phase 3D: Agentic-Native Live Run

- Run plan, skill, and memory tasks.
- Validate required session events such as skill invocation and memory events.
- Keep native-agentic evidence separate from core file-editing results.

## Phase 3E: Dogfood/Held-Out Seed Tasks

- Keep held-out source private.
- Require hidden fail-to-pass tests.
- Require task-quality notes.
- Run three stability trials before promotion.

## Phase 3F: Baseline/Ablation

Baseline and ablation remain blocked until runtime feature flags exist for:

- disabling memory;
- disabling plan mode;
- disabling subagents;
- disabling skills.

No ablation numbers should be reported until those controls exist at the public
CLI boundary.
