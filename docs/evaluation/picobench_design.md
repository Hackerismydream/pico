# PicoBench Design

## Positioning

PicoBench evaluates local coding agents by patch correctness and by the workflow that produced the patch: tool protocol, permission handling, sandbox behavior, read-before-write discipline, trace/report consistency, and resumable evidence.

Main line:

```text
PicoBench evaluates local coding agents not only by whether they produce correct patches,
but by whether they solve repository-level tasks through auditable, safe, resumable,
tool-grounded workflows.
```

## Five Layers

| Layer | Name | Purpose | Model | Entry |
|---|---|---|---|---|
| L0 | Deterministic Runtime Regression | Runtime/tool/report regression with `ScriptedModelClient`. | No live model | May import runtime |
| L1 | Human Scenario Gate | CLI/REPL/TUI/slash/approval/resume smoke. | Fake or live | Public entry |
| L2 | PicoBench-Core | Repo-level bugfix, feature, refactor, test, doc, config, safety tasks. | Live model | Public entry |
| L3 | PicoBench-Agentic | Plan, subagent, skill, memory, resume, TUI workflows. | Live model | Public entry |
| L4 | Live / Dogfood | Recent held-out tasks from real Pico/user workflows. | Live model | Public entry |

## Task Schema

First-phase schema is implemented in `pico/evaluation/benchmark_schema.py`.

Required fields:

- `schema_version`
- `suite`
- `tasks[].task_id`
- `tasks[].category`
- `tasks[].repo.fixture`
- `tasks[].prompt.text`
- `tasks[].execution.driver`
- `tasks[].execution.max_steps`
- `tasks[].tests.public`
- `tasks[].verifiers`

Supported drivers:

- `one_shot_cli`
- `repl`
- `pty`
- `tui`

Supported categories match the kickoff list: bugfix, feature, refactor, test generation/repair, documentation, configuration, CLI behavior, security, tool policy, sandbox, memory, resume, skill, subagent, plan mode, TUI, provider, and evidence.

## Metrics

External summary fields:

- `strict_pass_rate`
- `functional_pass_rate`
- `evidence_consistency_rate`
- `safety_violation_rate`
- `avg_tool_steps`
- `avg_cost_usd`

Strict pass is the public headline:

```python
strict_pass = (
    public_tests_pass
    and hidden_tests_pass
    and no_forbidden_side_effect
    and no_critical_policy_violation
    and report_trace_session_consistent
    and non_failure_stop_reason
)
```

Weighted score remains diagnostic only.

## Validators

Implemented first:

- `CommandVerifier`
- `PytestVerifier`
- `ForbiddenPathVerifier`
- `ChangedPathsVerifier`
- `SecretRedactionVerifier`
- `EvidenceVerifier`
- trace/report/task_state consistency checks

Later validators can add sandbox, memory, skill, subagent, and plan-mode specific assertions on top of `RunEvidence`.

## Runner

`scripts/run_picobench.py` loads a suite, creates one fresh workspace per task/run, initializes a git root, invokes Pico through a public command, runs validators, and writes:

```text
summary.json
summary.md
task_results.jsonl
logs/
workspaces/
evidence/
failures/
```

The runner rejects output directories inside the Pico repo. It does not import `Pico`.

## Baseline And Ablation

Required experimental variants:

- direct LLM patch
- Agentless-style localize/repair/validate
- pico-full
- pico-no-memory
- pico-no-plan
- pico-no-subagent
- pico-no-skills

First phase records the protocol. If runtime feature flags are missing, the ablation row should be marked `planned`; product runtime should not be bent just for a synthetic ablation.

## Failure Taxonomy

Primary categories:

- `functional_failure`
- `hidden_test_failure`
- `public_test_failure`
- `wrong_localization`
- `incomplete_patch`
- `overbroad_patch`
- `test_not_run`
- `tool_policy_violation`
- `permission_denied`
- `sandbox_failure`
- `path_escape_attempt`
- `secret_leak`
- `memory_contamination`
- `resume_mismatch`
- `skill_misuse`
- `subagent_scope_violation`
- `plan_mode_violation`
- `step_budget_exceeded`
- `timeout`
- `model_error`
- `provider_error`
- `trace_report_inconsistent`
- `runner_error`
- `flaky_environment`
- `task_quality_issue`

## Release Protocol

For a release candidate:

1. Run L0 deterministic regression.
2. Run L1 agentic gate.
3. Run L2 core suite against the chosen provider/model.
4. Inspect `summary.md` and each failure report.
5. Keep evidence bundles under an external output directory.
6. Publish only strict-pass numbers and clearly mark hidden/live task status.

## v0.1 Implementation Plan

First PR target:

- design docs and CCF audit shell
- schema loader
- validators
- trace consistency
- public-entry runner
- ten core fixtures
- 12 agentic gate task records
- summary JSON/Markdown
- tests for the new modules

Later work:

- convert all 50 v3 scenarios into task records
- hide hidden tests outside public fixtures
- add report card module and ablation runner
- add live/dogfood task curation workflow
