---
id: picobench-008
scope: evaluation
status: completed
depends-on:
  - picobench-003
  - picobench-004
  - picobench-005
  - picobench-006
  - picobench-007
authority-issue: 59
gates: [G0, G1, G2, G3, G4, G5, G6]
requires-live-provider: true
---

# PicoBench calibration and Ship campaign

## Objective

Expose the two checkout Make targets, freeze the final suite, execute the
campaign, and issue a reproducible Ship verdict without selecting for positive
results.

## Context

Calibration finds mechanical task, Verifier, Provider, and harness defects.
Its tasks are disjoint from the formal 24-task suite, and all Claim Rules are
frozen before the first real-provider call. Calibration and formal results
must not be used to tune thresholds, rewrite tasks for a positive result, or
selectively rerun treatment failures.

Owned paths:

```text
benchmarks/picobench/README.md
benchmarks/picobench/suites/agent_application_ship_1.yaml
benchmarks/picobench/__main__.py
benchmarks/picobench/campaign.py
Makefile
tests/test_picobench_campaign.py
```

Current-state documents may be updated only after the final evidence exists:

```text
benchmarks/README.md
docs/project-status.md
docs/feature-evidence.md
```

## Path

1. Add credential-free `make picobench-smoke` for contract, deterministic
   Tracks, local MCP, and report rebuild.
2. Before `make picobench` spends Provider budget, resolve the actual
   Provider/model, Tool Calling and usage-field support, seed support, maximum
   calls/tokens, tokenizer identity, and estimated worst-case cost across both
   Provider-call and block-attempt upper bounds. Abort when identity is unknown
   or the plan exceeds the Issue-approved ceiling.
3. Run the 64-Trial calibration on task ids disjoint from the formal suite:
   16 Context Trials, 24 Memory/Skill Trials, eight semantic-Memory-effect
   Trials, and 16 Tool/MCP Trials.
   Also run 34 disjoint Retrieval Cases: 10 user-Memory queries and eight Skill
   queries under all three configurations.
4. Repair only mechanical contract defects, create a new calibration digest,
   and rerun calibration. Do not change the already frozen Claim Rules in
   response to observed effect sizes.
5. Freeze the formal suite and run the final 216 planned base E2E Trials
   (48 Context, 72 Memory/Skill, 48 semantic-Memory-effect, and 48 Tool/MCP)
   plus 260 planned Retrieval Cases (80 user Memory and 180 Skill fusion).
6. Rotate arm order deterministically, apply at most two Provider-call
   attempts, rerun whole Provider/infra-contaminated Comparison or Retrieval
   Query Blocks at most once, and retain every attempt.
7. Require one terminal record for every planned Trial and Retrieval Case, all
   Pack coverage Gates, and an immutable-manifest-plus-record report rebuild.
8. Publish only positive metrics present in `cv-metrics.json`; retain complete
   valid negative measurements in `summary.json`.
9. Keep raw Trials, traces, Memory content, and generated reports outside Git.
   Extra block attempts are operational records and never increase the
   216-Trial or 260-Case planned denominators.
10. Build the distribution and prove PicoBench is absent from the wheel and
    `pico/` has no reverse benchmark dependency.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_campaign.py -q
uv run pytest tests/test_verify_distribution.py -q
make picobench-smoke
make picobench
```

Acceptance:

- the final campaign runs from a clean commit or clean worktree;
- task, fixture, retrieval corpus, query labels, Verifier, variant, retrieval
  configuration, workspace seed, lockfile, model, Tool catalog, tokenizer,
  effective Runtime config, executor, environment, timeout, Provider-call
  retry, block-attempt limits, and evidence digests are frozen;
- Provider preflight records the actual identity and hard-aborts above the
  approved cost ceiling;
- all 216 planned Trials and 260 Retrieval Cases have terminal records and
  required Packs meet Pair and retrieval coverage;
- no `task_failed` or `task_timeout` Trial is selectively rerun;
- PicoBench is absent from the wheel and no product module imports it;
- every CV number traces to its raw Trial, Pair, task, and Verifier;
- Pack-specific effects are not described as one unified overall lift;
- PicoBench Ship-1 is not used to close Issue #24, V-R0, or recovery Ship-2.
