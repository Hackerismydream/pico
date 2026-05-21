# PicoBench Task Authoring

## Task Quality Bar

A PicoBench task should test a repository-level coding workflow, not a single isolated function puzzle. Each task must have:

- a fresh fixture workspace;
- a clear user prompt;
- public tests;
- hidden tests when the task is functional or security-sensitive;
- expected changed paths;
- forbidden paths;
- evidence checks over `.pico/runs` and `.pico/sessions`;
- a primary category and quality metadata.

## Required Schema

Use `benchmarks/picobench-core-v1.yaml` as the reference. Required fields:

```text
schema_version
suite
tasks[].task_id
tasks[].category
tasks[].repo.fixture
tasks[].prompt.text
tasks[].execution.driver
tasks[].execution.max_steps
tasks[].tests.public
tasks[].verifiers
```

## Fixture Rules

Fixtures live under `tests/fixtures/picobench/<task_name>/`. They are copied into a benchmark workspace and committed before Pico runs. Do not design a task that edits the real Pico checkout.

Hidden tests may live in fixture `hidden_tests/` for the local open benchmark branch. For a public leaderboard, hidden tests should be mounted or injected at verification time from a private source.

## Verifier Rules

Use strict pass for external reporting:

```text
public tests pass
hidden tests pass
no forbidden side effects
evidence is consistent
non-failure stop reason
```

Do not count public test pass alone as solved.

## Safety Rules

Security tasks should focus on repair, detection, rejection, and isolation. Do not author tasks whose success requires generating executable offensive code.

## Review Checklist

- The initial fixture represents the bug or missing behavior.
- Public tests are enough to guide the model.
- Hidden tests add meaningful edge coverage.
- Expected changed paths are neither too loose nor impossible.
- The prompt does not reveal hidden tests.
- The task can run from a clean copied workspace with `python -m pytest`.
- Evidence validators read artifacts rather than runtime internals.
