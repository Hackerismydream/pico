---
id: codecairn-003
scope: evaluation
status: completed
depends-on:
  - codecairn-002
authority-issue: 70
external-depends-on:
  - codecairn:v02-002
gates: [M2, M4, M5]
requires-live-provider: true
---

# Close CodeCairn continuity and paired evidence

## Objective

Prove that the replacement works across process and installation boundaries,
then measure its task effect without selecting for a positive result.

The completed execution Goal is
[`pico-codecairn-joint-evidence-goal.md`](../pico-codecairn-joint-evidence-goal.md).
The Goal fixes execution order, immutable inputs, the paid authority barrier,
artifact ownership, and the final CodeCairn handoff.

GitHub Issue
[#70](https://github.com/Hackerismydream/pico-harness/issues/70)
authorizes the credential-free Delivery 1 at CNY 0 and conditionally
authorizes the paid campaign after the merged deterministic Gate freezes the
exact Provider/model, wheel pair, task set, Verifiers, CodeCairn profile,
claim rules, and cumulative CNY 100 hard ceiling. No second confirmation is
required when every frozen precondition passes. Missing credentials, an
unmetered external call, a failed Gate, or a projected worst-case total above
the ceiling remains a hard stop.

## Result

M2 and M4 passed against Pico `5318daa` and CodeCairn `a501fe2` through exact
installed wheels with no source-checkout imports. M5 formal experiment
`1c5496edfaa08212635f6218f9aaa55c3e942fcd1e79203a11a6b8c4d9b94623`
completed:

- 32/32 formal Trials and 16/16 valid Pairs;
- 16/16 CodeCairn task passes versus 0/16 Memory-off task passes;
- Recall@5 1.0, zero stale injections, zero cross-repository leakage, and zero
  Memory-off backend operations;
- byte-stable offline report rebuild;
- shared-ledger Provider charge 0.91294224 CNY, with 10.91294224 CNY total
  committed after the fixed 10 CNY reserve.

M5 is complete and measurement-valid. Positive Claim Eligibility is false
because every hard-negative query returned three memories, producing an
irrelevant-injection rate of 3.0 against the frozen maximum of 0.05. The final
handoff aggregate digest is
`8ac18e159899c62443ab3d4efb044c261d9cfed34f7b22b76f7f39860a188b2a`.
The durable result is recorded in
[Issue #70](https://github.com/Hackerismydream/pico-harness/issues/70#issuecomment-5128723096).

## Owned Pico paths

Expected scope:

```text
tests/integration/
scripts/verify_codecairn_continuity.py
benchmarks/picobench/
benchmarks/README.md
docs/evaluation/
docs/project-status.md
docs/feature-evidence.md
Makefile
```

Generated Trials, recalled content, traces, and reports remain outside Git.

## Path

1. Add deterministic Source Journal crash-tail and prefix-replay coverage.
2. Store one completed Pico Turn, stop the process, start a fresh process, and
   recall through the installed CodeCairn Adapter.
3. Verify repository A never recalls repository B content.
4. Verify Memory-off makes zero CodeCairn factory, lifecycle, recall, store,
   feedback, journal, import, and index calls while allowing cheap discovery.
5. Run V-O0 using temporary Pico and CodeCairn roots.
6. Build both wheels and run V-P0/installed-host parity without either source
   checkout.
7. Add a new PicoBench single-axis Pack:

   ```text
   control: memory.backend = null
   treatment: memory.backend = codecairn
   ```

8. Freeze 8-12 cross-session tasks, external deterministic Verifiers, two
   repetitions, Provider/model, budget, Tool set, Local Skills, retry policy,
   and cost ceiling.
9. Exercise store, import/index, fresh-process recall, and verifier in every
   treatment Trial.
10. Rebuild summary and CV metrics from raw terminal records. Preserve negative
    and inconclusive outcomes.

## Acceptance

- M2 and M4 pass on one compatible Pico/CodeCairn wheel pair;
- every planned Trial has a terminal record and every valid Pair changes only
  the Memory axis;
- reports bind both commits/versions, both wheel digests, task/verifier
  digests, config, model, and repository fixture;
- cross-repository leakage is zero;
- all Provider, infrastructure, timeout, task, and verifier failures remain in
  the denominator defined by the frozen plan;
- report rebuild performs no Runtime, CodeCairn, or Provider call;
- M5 is marked complete independently from positive Claim Eligibility;
- historical EverOS experiment ids and artifacts remain unchanged.

Only an eligible preregistered metric may be copied into resume material.
