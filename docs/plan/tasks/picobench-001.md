---
id: picobench-001
scope: evaluation
status: completed
depends-on: []
authority-issue: 59
gates: [G0, G1]
requires-live-provider: false
---

# PicoBench contract and plan identity

## Objective

Implement the smallest checkout-only core that turns a frozen experiment
specification into an immutable Trial matrix and digest-bound artifact layout.

## Context

Every later Task Pack needs the same identity, failure vocabulary, symmetric
Pair semantics, and rebuild rules. Implementing those separately would make
results incomparable. This task does not execute the real Runtime and does not
add a public `pico bench` command.

Owned paths:

```text
benchmarks/picobench/schema.py
benchmarks/picobench/canonical.py
benchmarks/picobench/plan.py
benchmarks/picobench/records.py
benchmarks/picobench/artifacts.py
benchmarks/picobench/protocol.py
benchmarks/picobench/registry.py
benchmarks/picobench/harness.py
benchmarks/picobench/__init__.py
tests/test_picobench_contract.py
```

## Path

1. Define `ExperimentSpec`, `ExperimentRef`, `TrialKey`,
   `RetrievalCaseKey`, `RetrievalQueryBlockKey`, `ComparisonBlockKey`,
   `AttemptKey`, `PairKey`, `TrialRecord`, `RetrievalCaseRecord`,
   `VerifierResult`, declarative `ClaimRule`, and the independent Runtime,
   delivery, verification, Trial, and retrieval state vocabularies.
2. Canonicalize source, suite, fixture, retrieval corpus, query labels,
   variant, retrieval configuration, Verifier, lockfile, model, budget,
   Provider-call max attempts, Comparison Block max attempts, Retrieval Query
   Block max attempts, tokenizer, effective Runtime configuration, executor,
   Python, platform, and evidence-schema identity.
3. Reject credentials, absolute user paths, timestamps, and output directories
   from the plan digest.
4. Compile the immutable Task-by-variant-by-repetition matrix, Comparison
   Blocks, Pair keys, and query-by-configuration Retrieval Case matrix. Permit
   one Trial to participate in multiple treatment-axis Pairs.
5. Implement the Pack protocol, Pack registry, and `run(spec)` orchestration
   over matrix expansion, digest-derived block order, isolated Trial calls,
   block-aware resume, symmetric rerun, and final reducer invocation.
6. Persist immutable Attempt Records and one atomic terminal Trial summary.
7. Resume only from a digest-matching resolved BlockResult. A lone Provider or
   infrastructure failure keeps the complete Comparison Block pending; reject
   missing, corrupt, asymmetric, or mismatched records. Stop after the frozen
   maximum block attempts and retain terminal contamination.
8. Derive the actual pairwise variant diff and fail any Pair whose diff is not
   exactly the Treatment Axis named by its PairKey.
9. Add a dummy Pack integration that exercises `run`, interrupted resume, and
   immutable-manifest-plus-record report rebuild without a real Provider.
10. Add a dependency/package boundary test: `pico/` must not import
    `benchmarks.picobench`, and PicoBench must remain outside the wheel.

## Verification

Run:

```bash
uv run pytest tests/test_picobench_contract.py -q
```

Acceptance:

- canonical input produces a stable digest across output roots;
- credentials and machine paths never enter the manifest or digest;
- every planned Trial has one stable TrialKey and explicit Pair memberships;
- every planned Retrieval Case has one stable key, query-block membership, and
  append-only attempts;
- corrupt or digest-drifted terminal records are not resumable;
- variant drift becomes `infrastructure_failure`;
- the dummy Pack completes `run -> resume -> rebuild` from the immutable
  manifest and stored evidence records;
- no product module imports PicoBench and the wheel boundary remains unchanged;
- Comparison-Block-aware Trial resume is never described as mid-Turn
  recovery.
