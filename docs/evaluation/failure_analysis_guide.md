# PicoBench Failure Analysis Guide

Use this guide after every live run. The goal is to preserve benchmark signal,
not to force every run green.

| Category | Meaning | Handling |
|---|---|---|
| `model_error` | Model returned invalid output, refused unexpectedly, or failed to follow the task | Inspect prompt, evidence, and model transcript; rerun only if provider instability is likely |
| `provider_error` | API auth, rate limit, network, quota, or provider protocol problem | Fix provider config or retry after provider recovery; do not edit task logic first |
| `public_test_failure` | Visible tests failed after Pico completed | Inspect workspace diff; likely product/model/task issue |
| `hidden_test_failure` | Hidden fail-to-pass tests failed | Preserve failure as benchmark signal; fix task only if hidden test is wrong |
| `evidence_inconsistency` | Trace, report, session, or artifact claims do not line up | Fix runner/evidence code before trusting score |
| `tool_policy_violation` | Required process rule failed, such as write before read or tests not run | Treat as strict failure even when tests pass |
| `test_not_run` | Expected test command was not observed or did not execute | Fix runner/task process verifier or model instruction |
| `timeout` | Task exceeded budget | Check whether budget is too low, task is too broad, provider is slow, or Pico loop is stuck |
| `task_quality_issue` | Fixture, metadata, or initial test condition is invalid | Fix or quarantine the task before using it in live runs |
| `runner_error` | Benchmark infrastructure failed independently of model behavior | Fix runner and rerun affected tasks |
| `product/runtime_bug` | Pico itself failed through a normal user path | File a Pico fix; keep benchmark evidence as repro |

## Action Choices

- Fix the task when the fixture, prompt, or expected behavior is wrong.
- Fix the runner when evidence, manifests, injection, or command handling is
  wrong.
- Fix Pico when the task exposes a real runtime/product bug.
- Tighten the task prompt when ambiguity produces invalid but understandable
  behavior.
- Increase step or time budget only when task complexity justifies it.
- Mark a task flaky only after repeated instability with the same commit and
  provider.
- Temporarily remove a task from a release run if it blocks measurement and has
  an unresolved quality issue.
