# PicoBench Current State Audit

Date: 2026-05-21

## Boundary

Pico already has two separate evaluation surfaces:

- `pico/evaluation/evaluator.py`: deterministic runtime regression using `ScriptedModelClient`. This is L0 and may import runtime objects such as `Pico`, `SessionStore`, and `RunStore`.
- `scripts/run_v3_human_scenario_gate.py`: public-entry human scenario gate. This is the model for L1/L2/L3 runners because it drives `uv run pico --cwd ...` and verifies only files under `.pico`.

PicoBench keeps that boundary. L0 can import runtime for deterministic regressions. L1/L2/L3/L4 must call public CLI/REPL/TUI surfaces and read evidence artifacts.

## Existing Evaluation Capabilities

| File | Current capability | Reuse in PicoBench |
|---|---|---|
| `pico/evaluation/evaluator.py` | Loads the old JSON benchmark, copies fixtures, runs scripted model outputs, writes benchmark artifact rows. | Keep as L0 deterministic runtime regression. Do not make it the public benchmark runner. |
| `pico/evaluation/metrics.py` | Aggregates benchmark rows and `.pico/runs/*` reports/traces into pass rate, attempts, tool counts, cache, status, security, duration metrics. | Reuse metric names in `summary.json`; extend later for cost and ablation. |
| `pico/evaluation/run_evidence.py` | Read-only adapter over `.pico/runs/<run_id>` and `.pico/sessions/*` evidence. | Use directly in validators and runner evidence copying. |
| `scripts/run_v3_human_scenario_gate.py` | Runs 12 gate scenarios or 50 full v3 scenarios through public process entrypoints. | Used by the `v3_human_gate` PicoBench driver for the priority agentic suite. |
| `release/v3/testing/01-test-design.md` | Defines human scenario coverage. | Source list for PicoBench-Agentic gate tasks. |
| `release/v3/testing/03-runner-and-evidence.md` | Defines runner trust boundary and artifact reading flow. | Treated as the runner contract. |
| `release/v3/learning/08-session-run-evaluation.md` | Explains session, run, task_state, trace, report, and deterministic evaluation. | Design basis for evidence consistency checks. |
| `benchmarks/coding_tasks.json` | Old L0 task schema. | Kept as compatibility input for existing evaluator; new suites use PicoBench schema. |

## Reusable Modules

- `RunEvidence.latest(workspace)` already locates latest run/session files.
- Existing `.pico/runs/<run_id>/task_state.json`, `trace.jsonl`, and `report.json` are enough to validate stop reason, tool counts, changed paths, security events, and artifact notices.
- The v3 human runner already solves workspace isolation with fresh directories and `git init -q`.

## New Modules Added

- `pico/evaluation/benchmark_schema.py`: PicoBench schema loader and normalizer.
- `pico/evaluation/validators.py`: command, pytest, forbidden path, changed path, secret redaction, and evidence validators.
- `pico/evaluation/trace_consistency.py`: recomputes counts from trace and compares report/task_state.
- `pico/evaluation/cli_runner.py`: public-entry benchmark runner implementation.
- `scripts/run_picobench.py`: CLI wrapper.
- `scripts/run_picobench_runtime.py`: L0 legacy-schema runner for `benchmarks/picobench-runtime-v1.json`.

## RunEvidence Interface

Current useful methods:

- `status()` and `stop_reason()`
- `changed_paths()`
- `tool_events()`, `tool_names()`, `has_tools()`
- `tool_error_codes()`
- `full_output_artifacts()`
- `runtime_reminder_contains()`
- `has_session_event()`

This is enough for first-phase PicoBench. More specialized checks can be added without importing runtime internals.

## Existing 50 Scenarios

The 50 scenarios already exist in `scripts/run_v3_human_scenario_gate.py`. PicoBench schema-izes the 12 priority gates in `benchmarks/picobench-agentic-v1.yaml` and runs them through that existing scenario gate instead of replacing the real setup/check logic with placeholder public tests. The full 50-scenario conversion remains a later pass.

## Trust Fixes Applied

- Core hidden tests now live under `tests/fixtures/picobench_hidden/<task_id>/hidden_tests/` and are injected only after Pico exits.
- Visible fixtures are committed before execution, so validators can use git diff instead of path-existence heuristics.
- Forbidden paths mean "must not be changed", not "must not exist".
- Claimed changed paths from `.pico` evidence are cross-checked with actual git changes.
- Single-task timeout/process failures are recorded as benchmark failures rather than crashing the whole suite.
- `pty` runs under a pseudo-terminal. Non-interactive `tui` runs are skipped with a reason rather than downgraded to REPL.
- L0 runtime regression remains a separate legacy evaluator flow.

## Runtime Logic Not To Touch

The benchmark work should not change:

- `pico/core/runtime.py`
- `pico/core/engine.py`
- tool permission and sandbox enforcement
- session/run storage semantics
- TUI presentation behavior

If a benchmark fails, first decide whether the failure is product behavior, runner evidence interpretation, live model drift, or task quality. Do not loosen product semantics to make a benchmark pass.
