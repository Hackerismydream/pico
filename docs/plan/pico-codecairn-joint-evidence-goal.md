# Codex Goal: close Pico-CodeCairn joint continuity and task evidence

Status: completed under GitHub Issue
[#70](https://github.com/Hackerismydream/pico-harness/issues/70). The issue
authorizes credential-free Delivery 1 at CNY 0 and conditionally authorizes
the paid campaign after the merged deterministic Gate freezes the exact live
contract. The aggregate CNY 100 ceiling covers the Agent Provider,
embeddings, reranking, and every other CodeCairn external call.

## Execution result

The final execution used Pico `5318daa`, CodeCairn `a501fe2`, and
`deepseek/deepseek-v4-flash`.

- Stage A J0-J2 passed with zero paid external calls.
- Calibration completed 4/4 Trials and 2/2 valid Pairs.
- Formal experiment
  `1c5496edfaa08212635f6218f9aaa55c3e942fcd1e79203a11a6b8c4d9b94623`
  completed 32/32 Trials and 16/16 valid Pairs.
- Treatment passed 16/16 task Verifiers versus 0/16 for Memory-off.
- Recall@5 was 1.0, with zero stale injections, zero cross-repository leakage,
  and zero Memory-off backend operations.
- Shared-ledger Provider charge was 0.91294224 CNY. Total committed was
  10.91294224 CNY including the fixed 10 CNY external-service reserve.
- `ship_complete=true` and `measurement_valid=true`.
- `positive_claim_eligible=false` because every hard-negative query returned
  three memories, producing an irrelevant-injection rate of 3.0 against the
  frozen maximum of 0.05.

The completion handoff aggregate digest is
`8ac18e159899c62443ab3d4efb044c261d9cfed34f7b22b76f7f39860a188b2a`.
Issue
[#70](https://github.com/Hackerismydream/pico-harness/issues/70#issuecomment-5128723096)
is the durable execution ledger. The starting pair below remains the
historical input to the Goal; the final pair and repairs are recorded in the
Issue.

## Objective

Use Pico as the canonical integration host to close the remaining
`codecairn-003` evidence boundary:

```text
installed Pico Runtime
  -> installed CodeCairn Memory Adapter
  -> normalized after-Turn store
  -> durable Source Journal and import
  -> process exit
  -> fresh-process recall
  -> repository isolation
  -> external deterministic Verifier
  -> memory-off versus CodeCairn paired evaluation
```

First implement and pass a credential-free installed continuity and isolation
Gate. Only after that Gate passes from a merged Pico commit may the Goal cross
an explicit authority barrier and run a paid Provider campaign.

The Goal may complete with a negative or inconclusive task-effect result. It
must not tune tasks, omit failures, or select a replacement baseline after
observing outcomes.

## Single-Goal boundary

This is the sole executable Goal for Pico-CodeCairn joint verification. It
owns two serial deliveries and one post-merge campaign:

1. implement the deterministic installed Gate and the frozen PicoBench Pack;
2. merge that implementation to Pico `main` and freeze the final wheel pair;
3. run the separately authorized paid campaign from that clean commit;
4. reconcile the resulting evidence and close the Pico task.

Do not create a second joint Runner or a second evaluation framework in the
CodeCairn repository. CodeCairn remains an immutable installed dependency
during this Goal. A CodeCairn defect stops the Goal and is fixed through a
separate CodeCairn delivery before the frozen pair is refreshed.

## Authoritative context

Read these sources before editing:

1. `AGENTS.md`
2. `CONTEXT-MAP.md`
3. `CONTEXT.md`
4. `docs/INDEX.md`
5. `docs/plan/README.md`
6. `docs/plan/tasks/codecairn-003.md`
7. `docs/specs/codecairn-memory-backend.md`
8. `docs/plan/analysis/codecairn-memory-replacement.md`
9. `docs/evaluation/README.md`
10. `docs/evaluation/picobench-ship-1.md`
11. `benchmarks/picobench/README.md`
12. `benchmarks/README.md`

The backend contract owns the cross-repository Interface and M0-M5 Gates. The
task card owns the Pico path and acceptance boundary. This Goal owns execution
order, immutable inputs, authority barriers, evidence layout, and final
handoff.

## Starting immutable pair

The implementation handoffs establish this starting pair:

| Input | Frozen value |
| --- | --- |
| Pico commit | `bbd518e22864b71e6abd91c79a86a08c90dca6bd` |
| Pico source locator | `git+https://github.com/Hackerismydream/pico-harness.git@bbd518e22864b71e6abd91c79a86a08c90dca6bd` |
| Pico wheel | `pico_harness-0.1.7-py3-none-any.whl` |
| Pico wheel SHA-256 | `8b879d37b1c039b49d2443ff49937a2a8ac755bb084c995d4a900c88426b4a0c` |
| Pico handoff SHA-256 | `08566e43d619be7f2c765592f16552dc9f77ef6ef594c1bc5e9b8784ece1b57c` |
| CodeCairn commit | `e993eb562cf1bb0b89490de4e91c2a56d79eb3be` |
| CodeCairn install specification | `codecairn @ git+https://github.com/Hackerismydream/CodeCairn.git@e993eb562cf1bb0b89490de4e91c2a56d79eb3be` |
| CodeCairn wheel | `codecairn-0.1.0-py3-none-any.whl` |
| CodeCairn wheel SHA-256 | `1c548a457fef6e16871125a59925e4dc4546af2d3fdfd7e7257b58a9a69f59c6` |
| CodeCairn handoff SHA-256 | `34ff9b882981068f43f3985b8f8b1e09cdee551d38752a24be4e48cc34d3f09e` |

Issue #70 binds redacted copies of both handoffs to immutable raw locators and
the digests above:

```text
Pico:
https://gist.githubusercontent.com/Hackerismydream/82cc0d713468d7770a47bb06885fa6f1/raw/135c981d97faa7dc7cc9e22007c64f26a43ce7e0/pico-handoff.json

CodeCairn:
https://gist.githubusercontent.com/Hackerismydream/82cc0d713468d7770a47bb06885fa6f1/raw/60211fa7b657bfc6043f922e336e5e5a833364e4/codecairn-handoff.json
```

Wheels may be acquired from an immutable release asset or rebuilt from the
exact source locator; the acquisition method, build command, filename, and
resulting digest are recorded in the Pair Manifest. Local temporary paths and
untracked handoffs are not valid locators.

The CodeCairn handoff tested an older Pico compatibility wheel. The later Pico
handoff is the current evidence that the same CodeCairn commit installs and
runs against the completed Pico-side replacement. The joint Gate must rebuild
and test both current wheels together; it may not reuse either handoff's smoke
as M2 or M4.

Before implementation, verify both handoff digests and all fixed identifiers:

| Contract | Value |
| --- | --- |
| Pico entry-point group | `pico.plugins` |
| Entry-point name | `codecairn` |
| Resource package | `codecairn.integrations.pico` |
| Plugin manifest ID | `codecairn-memory` |
| Memory backend contribution | `codecairn` |
| Backend factory | `codecairn.integrations.pico.backend:make_backend` |
| Source schema | `codecairn.pico.source.v1` |
| Turn boundary | `pico_turn_end` |

If either repository must change, stop. Land the fix in its owning repository,
regenerate that repository's final-main handoff, update the authority issue and
this table through a reviewed documentation PR, then restart at the pair audit.
Do not silently retarget a floating branch or newer `main`.

## Ownership

| Concern | Owner |
| --- | --- |
| `MemoryBackend` Interface and Runtime lifecycle | Pico |
| Session-normalized store slice | Pico |
| Source Journal, import, durable Memory, retrieval, and packing | CodeCairn |
| Installed Adapter and Plugin manifest | CodeCairn |
| Joint installed driver and deterministic Verifier | Pico |
| Cross-session task Pack and paired reducer | Pico |
| Provider usage, budget ledger, and claim Gate | Pico |
| Raw joint Trials and aggregate evidence | Pico |
| Adapter and import invariant evidence | CodeCairn |
| CodeCairn `v02-003` mirrored evidence state | final Pico joint handoff |

The joint implementation must exercise CodeCairn only through its installed
Adapter and operator commands. Pico benchmark code must not import CodeCairn
private storage, retrieval, importer, or ranking modules.

## Staged authority

Use Pico GitHub Issue #70 with two serial authority records.

### Stage A: credential-free Delivery 1

Before changing code:

1. create or confirm one Pico GitHub issue covering exactly
   `codecairn-003` and the eventual CodeCairn `v02-003` state synchronization;
2. record the starting immutable pair, both handoff digests, and immutable
   acquisition locations for the handoffs and wheels;
3. authorize deterministic Delivery 1 with Provider/model not applicable and
   a CNY 0 ceiling;
4. record the allowed Pico paths, J0-J3 acceptance, and the rule that no live
   Provider, embedding, reranking, or other paid external call is permitted;
5. write the issue number into `docs/plan/tasks/codecairn-003.md` and move it
   to `ready` when Stage A is complete.

Stage A authorizes only implementation, deterministic verification, review,
merge, and the post-merge freeze. It does not require task or Verifier digests
that Delivery 1 has not created.

### Stage B: paid paired campaign

After Delivery 1 merges and the post-merge pair, task set, and Verifiers are
frozen, append a second digest-bound record to the same issue. Before any live
call, Stage B must fix:

- Pico Agent Provider, endpoint class, and exact model;
- CodeCairn embedding, extraction, retrieval, and reranking profiles;
- which external CodeCairn calls are billable and how they are metered;
- task and Verifier digests;
- calibration and formal repetition counts;
- Tool catalog, Local Skill corpus, Context strategy, timeout, and retry
  policy;
- warning threshold and hard CNY ceiling;
- capability-level Measurement Validity and Positive Claim Eligibility rules.

The user pre-authorized the exact Stage B selection and hard-ceiling contract
recorded in Issue #70. After Delivery 1 merges, the executor may materialize
the digest-bound approval from the final frozen inputs and continue without a
second confirmation. This pre-authorization does not permit any drift in the
Provider/model, matrix, retry rules, claim rules, or budget ceiling.

Issue #59's historical CNY 100 PicoBench authority does not fund this Goal.
Issue #65 authorizes only the completed implementation deliveries. Missing or
ambiguous paid authority is a hard stop, not permission to use a convenient
default.

## Delivery 1: deterministic joint Gate and frozen Pack

Create one delivery from the latest Pico `main`. Expected ownership is:

```text
tests/integration/test_codecairn_continuity_e2e.py
scripts/verify_codecairn_continuity.py
benchmarks/picobench/packs/codecairn_memory/
benchmarks/picobench/tasks/codecairn_memory/
benchmarks/picobench/suites/codecairn_memory_effect.yaml
benchmarks/picobench/
benchmarks/README.md
docs/evaluation/
docs/specs/codecairn-memory-backend.md
docs/plan/tasks/codecairn-003.md
Makefile
```

Reuse PicoBench experiment planning, Trial isolation, usage recording, budget
ledger, terminal records, pair coverage, reducer, and offline rebuild modules.
Do not create a parallel campaign engine.

### J0: pair and environment integrity

The driver must:

- accept exact Pico and CodeCairn wheel paths plus both handoff paths;
- verify every recorded digest before installation;
- create an isolated Python 3.12 environment with an empty `PYTHONPATH`;
- prove neither source checkout is importable;
- give every case an isolated Pico home, CodeCairn root, Git repository, and
  Workspace;
- record installed distributions, direct-url identities, entry points, Plugin
  inventory, Python/platform identity, and environment digest;
- reject a dirty source tree, mutable VCS reference, mismatched wheel, missing
  handoff, unknown schema, or incompatible Plugin inventory.

The resulting Pair Manifest uses one canonical JSON form and includes both
commits, wheels, handoffs, contract identifiers, and environment identity.

### J1: installed continuity

Using only installed distributions:

1. initialize repository A with `codecairn init`;
2. start Pico with `memory.backend = "codecairn"`;
3. submit one deterministic Turn through Runtime Assembly and Spine;
4. persist the Session-normalized after-Turn slice;
5. require the Adapter store call to return only after the journal prefix is
   durable and deterministic read readiness is reached;
6. stop Pico and complete backend teardown;
7. start a fresh process in repository A;
8. recall the expected context through Pico's user-memory track;
9. pass an external deterministic Verifier;
10. retain expected and observed Memory IDs, source URI, journal cursor, import
    cursor, index cursor, consuming Turn, and terminal outcome.

Do not count a direct Adapter method call, source-checkout import, same-process
cache hit, or model assertion as installed cross-process continuity.

### J2: isolation, replay, and failure

The credential-free Gate must also prove:

- repository A content is absent from repository B;
- identical Pico user, agent, Session, and conversation identifiers do not
  cross repository identity;
- `memory.backend = null` performs zero CodeCairn factory, lifecycle, recall,
  store, feedback, journal, import, and index operations;
- replaying one committed Source Journal prefix creates zero duplicate Episode
  or Memory identities;
- a truncated uncommitted tail is recovered or rejected according to the
  Source Journal contract without importing it;
- a committed-prefix conflict fails explicitly;
- missing initialization, workspace mismatch, malformed journal, import
  failure, index-not-ready state, and backend stop failure retain typed failure
  classes and remediation;
- Local Skills use the same corpus and BM25 path with CodeCairn selected and
  Memory off;
- Session, Memory, Trace, and Delivery are not described as one transaction;
- no case claims mid-Turn recovery or exactly-once external side effects.

### J3: Pack and report discipline

Add a new single-axis Pack:

```text
control:   memory.backend = null
treatment: memory.backend = codecairn
```

The Pack must use cross-session tasks whose treatment arm actually performs:

```text
Session A task
  -> Pico store
  -> CodeCairn journal/import/index
  -> process exit
  -> fresh Session B process
  -> CodeCairn recall
  -> Pico Context injection
  -> task artifact
  -> external deterministic Verifier
```

Calibration and formal task IDs must be disjoint. Verifier code and expected
answers remain outside the Agent-accessible Workspace. Task, Verifier,
workspace seed, variant, Tool catalog, Local Skills, and claim-rule digests are
frozen before any live preflight.

Every Trial records:

- terminal class and deterministic Verifier result;
- expected and observed Memory IDs plus provenance;
- repository identity hash and isolation result;
- Source Journal, import, and index cursors;
- main-Agent and auxiliary attributable model usage;
- CodeCairn external-call usage or explicit non-billable identity;
- Tool calls, repeated repository reads, Memory failures, and latency;
- bounded trace and artifact locations.

The reducer reports run-level and task-level pass rates, paired task delta,
Recall at the pre-registered K, token and latency deltas, Tool-call and repeated
read deltas, Memory-induced regressions, cross-repository leakage, Pair
coverage, and every terminal failure class.

### Delivery 1 verification and merge

Add credential-free entry points such as:

```text
make verify-codecairn-continuity
make picobench-codecairn-smoke
```

They must not resolve a live Provider or create a paid external call. Run the
task's focused tests, retained affected tests, current distribution Gate, and
`make check-large-files`. Build both wheels and execute J0-J2 in a clean
environment.

Commit, self-review, create the PR, wait for required checks, and squash-merge
Delivery 1 before any paid call. The merge marks `codecairn-003` in progress,
not completed.

## Post-merge freeze

After Delivery 1 merges:

1. fetch final Pico `origin/main` and freeze its 40-character commit;
2. create a clean checkout at exactly that commit;
3. rebuild the Pico wheel and record its SHA-256;
4. resolve or rebuild the exact CodeCairn input from its immutable install
   specification;
5. rerun J0-J2 with no source checkout imports;
6. generate a new immutable Pair Manifest and deterministic summary;
7. require all deterministic integrity Gates to pass before projecting or
   approving paid spend.

If a failure requires code changes, fix it through a reviewed PR and repeat
the post-merge freeze. A pre-squash feature commit is not a valid campaign
identity.

## Paid authority barrier

Do not perform a live preflight, calibration Trial, Provider retry, embedding
call, rerank call, or formal Trial until:

- J0-J2 pass on the frozen post-merge wheel pair;
- the authority issue contains the complete live contract;
- a digest-bound approval record freezes the projected request and token
  bounds for both Pico and CodeCairn external calls;
- cumulative existing spend, reserved maximums, calibration, retries, and the
  formal matrix fit below the hard ceiling;
- the frozen approval record matches the conditional authorization in Issue
  #70.

Use PicoBench's existing fail-closed budget reservation and high-water ledger.
Incomplete usage is an infrastructure failure and does not release the
reservation for discretionary retries.

## Campaign execution

### Live preflight

Prove the exact Agent Provider/model supports the required Tool Calling and
complete usage fields. Prove the selected CodeCairn profile reaches the
required store, import/index, and fresh-process recall state. The preflight may
not substitute for a planned Trial.

### Calibration

Run only the frozen calibration task IDs. Use calibration to find
infrastructure, budget, timeout, or verifier defects. Do not rewrite task
success criteria, expected answers, or the formal task set in response to
treatment performance.

If tracked code, task semantics, variant behavior, or claim rules change,
invalidate the approval, merge the change, rebuild the Pair Manifest, and
repeat the authority barrier.

### Formal paired campaign

The minimum formal matrix is:

```text
8 cross-session tasks
x 2 Memory variants
x 2 repetitions
= 32 planned Trials
```

Do not call repetitions seeds unless the Provider accepts and records a seed.
Alternate or randomize Pair order. Model, parameters, Context strategy, Tool
catalog, Local Skills, budgets, timeout, retry policy, base Workspace, and
repository identity remain identical within each Pair.

Only a missing or corrupt complete Pair may be rerun, and both arms receive the
same whole-Pair retry policy. Provider, infrastructure, timeout, task,
cancelled, verifier, and inconclusive outcomes remain in their declared
denominators.

Every planned Trial must produce one terminal record. If valid Pair coverage is
below the pre-registered threshold, Ship Completeness may still be true but
Measurement Validity is false and no product delta is exported.

## Artifact layout

All generated data remains ignored:

```text
.pico/evidence/codecairn-joint/<experiment-id>/
  pair-manifest.json
  approval.json
  deterministic/
    continuity.json
    isolation.json
    replay.json
    failure-taxonomy.json
  trials/
  traces/
  artifacts/
  paired-results.json
  summary.json
  cv-metrics.json
  codecairn-v02-003-handoff.json
  REPORT.md
```

`summary.json`, `cv-metrics.json`, and `REPORT.md` must be rebuilt only from
sealed terminal records. Rebuild performs no Runtime, CodeCairn, Provider,
embedding, or reranking call and is byte-stable except for explicitly
non-semantic generation fields.

The CodeCairn completion handoff records both commits and wheel digests,
deterministic J0-J2 results, campaign identity, aggregate digest, and honest
Ship Completeness, Measurement Validity, and Positive Claim Eligibility. It
does not copy or relabel historical CodeCairn or EverOS evidence.

## Delivery 2: evidence reconciliation and state sync

After the campaign:

1. update `docs/plan/tasks/codecairn-003.md` to `completed` only if M2, M4, and
   M5 all satisfy their acceptance definitions;
2. update `docs/project-status.md`, `docs/feature-evidence.md`,
   `docs/roadmap.md`, `docs/evaluation/`, and benchmark READMEs with concise,
   commit-bound results;
3. preserve `ship_complete`, `measurement_valid`, and
   `positive_claim_eligible` as independent fields;
4. copy into resume material only metrics exported by `cv-metrics.json`;
5. return the final Pico joint handoff digest for a separate CodeCairn
   `v02-003` documentation state-sync;
6. leave raw Trials, recalled content, secrets, traces, and report assets
   outside Git.

A negative task delta can complete M5 when the campaign is intact. It cannot
be rewritten as improvement. A deterministic continuity pass does not imply
task uplift.

## Failure routing

| Finding | Action |
| --- | --- |
| Pico Runtime, Session, Context injection, config, usage, or Delivery defect | stop the campaign and fix Pico in a reviewed PR |
| CodeCairn Adapter, Source Journal, import, index, retrieval, or packing defect | stop the Goal and open a separate CodeCairn delivery |
| cross-repository Interface mismatch | version the contract, update both handoffs, and restart from the pair audit |
| task, Verifier, reducer, or budget-ledger defect | fix Pico, invalidate affected approval, and restart the relevant frozen phase |
| Provider or external infrastructure failure | retain the terminal class and apply only the pre-registered symmetric retry policy |
| negative product result | complete the evidence Ship with `positive_claim_eligible = false` |

Never fix a CodeCairn defect through a Pico monkey patch, local source
dependency, copied private module, or untracked compatibility shim.

## Hard constraints

- Do not modify the CodeCairn repository from this Goal.
- Do not use floating branches, local path dependencies, or dirty checkouts.
- Do not import from either source checkout in an installed claim.
- Do not add EverOS fallback, dual write, or historical-result relabeling.
- Do not replace Local Skills or route them through CodeCairn.
- Do not create another Runtime, Context Engine, Session model, benchmark
  engine, budget ledger, or report reducer.
- Do not expose Verifier code or expected answers to the Agent Workspace.
- Do not treat `semantic_pending`, an empty recall, or a direct Adapter call as
  successful task continuity.
- Do not run paid calls before the authority barrier.
- Do not selectively rerun a weaker arm or delete terminal failures.
- Do not claim crash recovery, external exactly-once behavior, production SLO,
  formal Pico v1 release, or task improvement outside the measured scope.

## Definition of done

This Goal is complete only when:

1. one dedicated authority issue contains a completed CNY 0 Stage A and an
   explicitly approved Stage B that owns the immutable campaign pair, live
   configuration, task matrix, claim rules, and hard spend ceiling;
2. the deterministic joint driver installs both wheels without source leakage;
3. cross-process store and recall pass through Pico Runtime and the installed
   CodeCairn Adapter;
4. repository isolation, Memory-off zero operations, replay idempotency,
   crash-tail behavior, typed failures, and Local Skill parity pass;
5. Delivery 1 is reviewed, merged, and rerun from its final Pico `main`
   commit;
6. every paid request is covered by a digest-bound approval and cumulative
   budget ledger;
7. every planned formal Trial has one retained terminal record;
8. the offline reducer reconstructs the same aggregate from raw records;
9. M2, M4, and M5 each receive an explicit result independent of positive
   claim eligibility;
10. only eligible metrics enter `cv-metrics.json`;
11. current Pico docs are reconciled without committing generated report
    assets;
12. the final handoff is sufficient for CodeCairn to synchronize the mirrored
    `v02-003` evidence state without rerunning or reinterpreting Pico's
    campaign.

Do not stop after adding tests, passing a direct Adapter smoke, opening a PR,
or completing only one arm. Finish the develop-review-merge cycle,
post-merge deterministic rerun, authorized paired campaign, offline rebuild,
and evidence reconciliation. Report negative and inconclusive outcomes
without weakening them.
