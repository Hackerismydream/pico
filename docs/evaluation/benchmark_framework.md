# PicoBench Benchmark Framework

PicoBench is an internal evaluation stack for Pico's public CLI/runtime
boundary. It is not a public leaderboard. Scores are only comparable when the
same commit, provider, model, task set, approval mode, sandbox mode, and hidden
test policy are used.

## Levels

| Level | Suite | Purpose | Provider required |
|---|---|---|---|
| L0 | Runtime regression | Deterministic checks for benchmark runner plumbing and locked fixtures | No |
| L1 | Human scenario gate | Existing v3 human-scenario acceptance wrapper, delegated through the scenario gate driver | Optional |
| L2 | PicoBench-Core | Native file-editing and bugfix tasks with visible fixtures and hidden fail-to-pass tests | Yes for live runs |
| L3 | PicoBench-Agentic | Native Pico behaviors such as planning, skills, memory, and session events | Yes for live runs |
| L4 | Live/dogfood | Controlled live and held-out tasks with stability and contamination controls | Yes |

## Public Entry Boundary

L2-L4 tasks run through `scripts/run_picobench.py`, which invokes Pico through
the same public CLI surface used by normal users. The L0 runtime regression uses
`scripts/run_picobench_runtime.py` because it has a separate deterministic
schema and does not call an LLM provider.

## Task Structure

Each core task has:

- a visible fixture under `tests/fixtures/picobench/`;
- a hidden fixture under `tests/fixtures/picobench_hidden/`;
- public tests that describe the expected behavior without fully specifying the
  private edges;
- hidden fail-to-pass tests injected only after Pico exits;
- process and evidence verifiers.

Hidden tests are benchmark assets. They must not be published as live/dogfood
held-out tasks or uploaded into public artifacts.

## Evidence Consistency

Each run preserves enough evidence to audit a score:

- command logs;
- workspace state;
- Pico run report;
- trace;
- task state;
- session and session events;
- copied evidence bundles;
- summary and compact summary.

Evidence consistency checks compare the trace, report, session events, changed
paths, and claimed outputs. A task should not be counted as a strict pass if the
functional tests pass but the evidence is missing or contradictory.

Evidence mode is explicit:

- `evidence_mode=native`: L2/L3 PicoBench tasks run through the Pico public
  entry boundary and must produce native report, trace, task state, session, and
  session-event evidence.
- `evidence_mode=delegated_human_gate`: L1 v3 human-gate tasks delegate to the
  existing scenario gate and do not emit the same native PicoBench evidence
  bundle.
- `evidence_mode=mixed`: summary-level mode when a report contains both native
  and delegated tasks.

Strict pass can be recorded for both native and delegated suites, but evidence
consistency is calculated only for native PicoBench tasks. Delegated human-gate
evidence consistency is `not_applicable`, not `0.0`.

## Task Quality

`pico/evaluation/task_quality.py` and
`scripts/check_picobench_tasks.py` enforce suite hygiene:

- minimum task count;
- visible/hidden fixture separation;
- required metadata;
- required public and hidden tests;
- optional executable checks for public and hidden tests;
- initial all-green detection.

Executable quality checks are intended for subsets because they run task tests
inside copied fixtures.

## Process Validators

Process validators catch behavior that pure tests miss:

- required tool sequence;
- must run tests;
- must read before write;
- required trace event;
- required session event;
- artifact existence from fixed paths, trace artifacts, or manifests.

These validators make benchmark results about agent process quality, not only
final file contents.

## Report Card

The report card writes:

- `summary.json`;
- `summary_compact.json`;
- `summary.md`;
- `task_results.jsonl`;
- category breakdown;
- timeout count;
- duration p50/p95;
- failure taxonomy.

Only `strict_pass_rate` is treated as the main benchmark result. Functional
pass rate is diagnostic.

## Failure Taxonomy

Failures are grouped into runner, provider, model, task, evidence, tool policy,
test, timeout, and product/runtime categories. The category is used to decide
whether to fix a task, fix the runner, fix Pico, adjust provider settings, or
mark a live task flaky.

## Ablation Status

Ablation remains planned-only. Real ablation numbers require public runtime
feature flags for disabling memory, plan mode, subagents, and skills through
the same CLI boundary used by normal benchmark tasks.
