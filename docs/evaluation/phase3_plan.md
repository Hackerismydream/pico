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

Status on 2026-05-22: completed once on DeepSeek at commit
`068318fea6d5aee29353656464c598667f678466`. Result: 10 tasks, 8 strict
passes, 2 strict failures, pass rate `0.8`. Both failures were
`hidden_test_failure` on `core_027` and `core_028`; evidence consistency was
`1.0`. Failure triage is in `docs/evaluation/phase3b_failure_triage.md`.

## Phase 3C: Full 30-Task Core Live Run

- Run all 30 core tasks only after Phase 3A and 3B are stable.
- Preserve full evidence bundles.
- Review hidden test failures before changing any task.

Status on 2026-05-23: completed once on DeepSeek at commit
`2372068723af8b1c06b3e43362193e91fdbe3c41`. Result: 30 tasks, 22 strict
passes, 8 strict failures, pass rate `0.7333333333333333`. Evidence
consistency was `1.0`; failures were 7 `hidden_test_failure` rows and 1
`tool_policy_violation`.

Status update on 2026-05-24: formal triage is complete in
`docs/evaluation/phase3c_core30_failure_triage.md`. Targeted stability reruns
completed twice on DeepSeek. Six tasks (`core_016`, `core_018`, `core_019`,
`core_023`, `core_027`, `core_028`) failed consistently as hidden-test
benchmark signal. `core_029` passed both targeted reruns after the original
process-policy failure; `core_030` passed one targeted rerun and failed the
other, so both are stability-sensitive.

## Phase 3D: Agentic-Native Live Run

- Run plan, skill, and memory tasks.
- Validate required session events such as skill invocation and memory events.
- Keep native-agentic evidence separate from core file-editing results.

Status on 2026-05-23: completed once on DeepSeek at commit
`2372068723af8b1c06b3e43362193e91fdbe3c41`. Result: 3 tasks, 2 strict
passes, 1 strict failure. The failure was `trace_report_inconsistent` on the
memory example: functional memory behavior passed, but the evidence bundle was
missing `report_path`, `trace_path`, and `task_state_path`.

Status update on 2026-05-24: `agentic_native_memory_001` was fixed by replacing
the slash-only prompt with a remember-plus-confirmation turn and increasing the
step budget. DeepSeek rerun at `/tmp/picobench-agentic-native-rerun2` passed
3/3 with evidence consistency `1.0`.

## Phase 3D.1: Agentic-Native v1 Expansion

- Expand native scenarios from 3 to 8.
- Keep native evidence separate from delegated human-gate evidence.
- Classify functional, evidence, step-budget, and task-design failures
  separately.

Status on 2026-05-24: `benchmarks/picobench-agentic-native-v1.yaml` contains
8 tasks. DeepSeek live smoke at `/tmp/picobench-v03-agentic-native` completed:
8 tasks, 6 strict passes, 2 strict failures, pass rate `0.75`, evidence
consistency `1.0`. Failures were `agentic_native_resume_001`
(`public_test_failure`) and `agentic_native_subagent_001`
(`step_budget_exceeded`). These are v1 readiness blockers, not evidence
blockers.

## Phase 3E: Dogfood/Held-Out Seed Tasks

- Keep held-out source private.
- Require hidden fail-to-pass tests.
- Require task-quality notes.
- Run three stability trials before promotion.

Status on 2026-05-24: core suite expanded from 30 to 40. Ten new core tasks
include 8 multi-file tasks and 6 Pico dogfood-derived tasks. New-core
executable quality passed for all 10 tasks. DeepSeek live smoke passed 9/10
strict with evidence consistency `1.0`; only `core_032` failed hidden report
manifest edges.

## Phase 3F: Baseline/Ablation

Baseline and ablation remain blocked until runtime feature flags exist for:

- disabling memory;
- disabling plan mode;
- disabling subagents;
- disabling skills.

No ablation numbers should be reported until those controls exist at the public
CLI boundary.
