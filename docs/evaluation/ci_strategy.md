# PicoBench CI Strategy

Default CI intentionally does not use an LLM provider key. That is the correct
design: pull-request and push checks should be deterministic, cheap, and safe
for untrusted code paths.

## Tier 0: No-Key CI

Runs on pull requests and pushes:

- schema tests;
- validator tests;
- task quality tests;
- report card tests;
- static task quality gate;
- executable task-quality subset;
- L0 runtime regression.

Tier 0 must not call a real provider, read provider secrets, or depend on an
external model service.

## Tier 1: Manual Live Smoke

Runs only through `workflow_dispatch`:

- protected GitHub Environment: `picobench-live`;
- provider secrets from environment or repository secrets;
- small task subset, normally 1-3 core tasks;
- uploaded summary and evidence artifacts.

This tier verifies that the live provider path works without making live
provider calls part of normal CI.

## Tier 2: Release Live Benchmark

Manual release operation:

- larger core task set;
- selected agentic-native task set;
- complete evidence bundle;
- redacted provider config;
- execution log entry;
- failure analysis.

Hidden tests and private held-out tasks must not be published as source or CI
artifacts.

## Tier 3: Dogfood/Live Held-Out

Private benchmark operation:

- private seed tasks;
- stability checks, preferably three runs per task;
- contamination controls;
- task-quality notes;
- manual review before promotion into any stable suite.

## Safety Rules

- Do not use `pull_request_target` for live provider runs.
- Do not pass provider keys as CLI arguments.
- Do not print provider keys.
- Do not upload raw hidden test source.
- Do not turn live failures into green CI by fabricating results.
