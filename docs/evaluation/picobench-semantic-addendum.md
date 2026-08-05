# PicoBench semantic retrieval addendum

Status: completed historical checkout-only evaluation track. The EverOS
Runtime and Makefile entry points described below were removed from current
Pico; reproduce them only from the recorded source commit. This document is
not CodeCairn evidence.

This addendum closes one evidence boundary in PicoBench Ship-1. The
credential-free Retrieval Cases proved Pico's contracts but did not prove
the former production EverOS semantic retrieval. The addendum ran held-out
natural-language Memory and Skill queries through the production EverOS
markdown writers, Cascade indexer, LanceDB recallers, Pico `EverosBackend`,
Local BM25 source, and `SkillForgeRouter`.

It does not replace the frozen Ship-1 task campaign. Its artifacts and
claim output are separate, and it makes no end-to-end task-effect,
final-Skill-injection, or task-recovery claim.

## Evidence sequence

The first semantic campaign is retained as a negative development result:

- experiment id:
  `1336036d67d0c4ddf6142d894ed1cbfc1019d85d4624bd878d6a8c4e3b88018a`;
- source commit: `68c431598da86750c64b726dea23029086ba9efd`;
- report digest:
  `7d5bff56fca4d1cb5cc64984cb8ce0aa5f1c6f6d1b5ea4500f838d933067d0e1`;
- Memory Recall@5 was `1.0`, but Precision@5 was `0.392` and irrelevant
  injection was `0.608`;
- Skill fused Recall@5 was `0.625`, equal to both single sources.

Those records were not deleted or relabeled. The v2 suite binds the negative
experiment identity and report digest into its tracked manifest, uses disjoint
calibration and formal identifiers, and evaluates held-out natural-language
queries.

The final-history v1 replay at source commit
`e6c790e37d707f74c44896dbcba9de9ee4ad8327` produced experiment
`813a8b8ba25a2e55cc1cfd5b033fc65d1abc7108e6cadb5d13d2bf42210efce4`
and report digest
`6fd92a19ba82d0cc06837ae99dff166cacf0c4cbcea71608d46264fe1ff145df`.
Its 260/260 terminal records reproduced the negative boundary: Memory
Recall@5 was `1.0`, Precision@5 was `0.3897`, irrelevant injection was
`0.6103`, and Skill fusion did not improve on either `0.625` single source.
The replay remains ineligible and does not replace the preregistered anchor.

## Frozen v2 execution path

```text
Natural-language corpus
  -> EpisodeWriter / AgentSkillWriter
  -> CascadeOrchestrator
  -> real embedding provider
  -> EverOS SearchManager
     user memory: HYBRID
     agent skill: VECTOR
  -> Pico EverosBackend
  -> Local BM25 + EverOS vector + weighted RRF
  -> Memory context injection / Skill candidate retrieval
  -> external reducer
```

User Memory is evaluated at the context-injection stage. Skill is evaluated
at the candidate-retrieval stage before the optional LLM gate. The v2 suite
does not evaluate final Skill injection, and `cv-metrics-semantic.json`
records that boundary explicitly.

The v2 thresholds and ranks were preregistered as:

- user `min_score`: `0.65`;
- Memory top K: `1`;
- agent vector `radius`: `0.55`;
- Local BM25 `min_score`: `4.0`;
- Skill candidate top K: `10`;
- Local and EverOS fusion weights: `1.0` and `0.9`.

The product defaults remain backward compatible. The score thresholds apply
only when explicitly configured by the evaluation plan.

## Frozen v2 data and denominators

Calibration and formal task identifiers and query text are disjoint.
Formal records use these denominators:

| Scope | Positive queries | Hard-negative queries | Configurations | Records |
|---|---:|---:|---:|---:|
| Memory context injection | 50 | 30 | 1 | 80 |
| Skill candidate retrieval | 40 | 20 | 3 | 180 |
| Total | | | | 260 |

Of the 260 records, 200 traverse production EverOS retrieval and 60 are the
Local-only BM25 control arm.

Skill queries run under:

- `local_only`: Local BM25;
- `everos_only`: production EverOS vector recall;
- `fused`: Local BM25 plus EverOS vector recall through weighted RRF.

The report keeps source, rank, score, RRF contribution, and consuming query
identity without copying Memory or Skill content into the public summary.

## Budget and paid-call boundary

Calibration and formal execution share one cumulative `5 CNY` hard cap.
Preflight computes a conservative bound from corpus and query characters,
the preregistered embedding price ceiling, an exchange-rate multiplier,
a safety multiplier, and one `0.5 CNY` reserve. It makes no Provider call.

The v2 commands are:

```bash
make picobench-semantic-v2-preflight

PICOBENCH_SEMANTIC_V2_PAID_APPROVAL=<calibration-approval-digest> \
  make picobench-semantic-v2-calibration

PICOBENCH_SEMANTIC_V2_CALIBRATION_ROOT=<calibration-experiment-root> \
  make picobench-semantic-v2-formal-preflight

PICOBENCH_SEMANTIC_V2_PAID_APPROVAL=<formal-approval-digest> \
PICOBENCH_SEMANTIC_V2_CALIBRATION_ROOT=<calibration-experiment-root> \
  make picobench-semantic-v2
```

The completed final-history v2 ledger recorded 720 cumulative embedding calls
across calibration and formal execution, zero open reservations, 0.21468672
CNY in conservatively estimated Provider cost, and 0.71468672 CNY committed
including the fixed reserve. These are budget-control estimates rather than
Provider invoice amounts.

## Isolation and artifacts

Each process uses a fresh temporary `EVEROS_ROOT`, initializes isolated
SQLite and LanceDB stores, writes the controlled corpus, runs one Cascade
sync, performs retrieval, and disposes both stores. State is not reused
between calibration and formal tracks.

Artifacts live under:

```text
.pico/evidence/picobench-semantic-v2/<experiment-id>/
  manifest.json
  records/<suite>/<query>/<configuration>.json
  summary.json
  cv-metrics-semantic.json
```

`summary.json` and `cv-metrics-semantic.json` are rebuilt entirely from the
immutable manifest and case records. Artifact writes are atomic. Rebuilds
validate the suite digest and exact planned key set. A complete experiment is
rebuilt without a Provider call; a partial, stale, or tampered root fails
closed. The addendum never writes the frozen task campaign's
`cv-metrics.json`.

## v2 claim gates

Formal Memory metrics are eligible only when:

- all 80 records are measurable;
- production embedding evidence is valid;
- Recall@1 is at least `0.80`;
- irrelevant and hard-negative injection are at most `0.05`;
- stale injection and cross-workspace leakage are zero.

Precision@1 is reported as a diagnostic. It is not a separate gate because the
irrelevant-injection threshold already requires precision of at least `0.95`
over eligible outputs.

Formal Skill candidate metrics are eligible only when:

- all 180 records are measurable;
- production embedding evidence is valid;
- fused Recall@10 is at least `0.80`;
- fused Recall@10 exceeds the better single source by at least `0.05`;
- cross-workspace leakage is zero;
- fused RRF scores and source contributions are auditable.

Raw hard-negative abstention and final Skill injection use separate claim
flags. Failure of either does not invalidate candidate-retrieval quality, and
candidate-retrieval quality must not be described as final injection quality.

Calibration never emits CV-eligible metrics. Failed thresholds produce
`claim_eligible=false`; records remain retained.

## Completed v2 result

The formal v2 campaign ran from clean source commit
`e6c790e37d707f74c44896dbcba9de9ee4ad8327` using
`everos/text-embedding-v4`.

The formal experiment id is
`98bb1e3cca2d1ee45dbebebef7f44db87fbea8ea23d1ea177843df6ba3ca2a1b`:

- `ship_complete=true`;
- `production_evidence_valid=true`;
- all 260 planned records are measurable;
- Memory Recall@1 and Precision@1 are both `1.0`;
- Memory irrelevant and hard-negative injection are both `0`;
- Memory stale injection and cross-workspace leakage are both `0`;
- Skill fused candidate Recall@10 is `1.0`, versus `0.625` for Local-only
  and `0.625` for EverOS-only;
- fused candidate retrieval improves over the better single source by `0.375`,
  or 37.5 percentage points;
- Skill candidate cross-workspace leakage is `0`;
- repeated raw-artifact rebuilds produce report digest
  `f2ac0ec1c81dafac4f81d0041af700f2a6f3fae9eb8e9b83c58d50d79d20f1a5`.

`memory_claim_eligible=true` and
`skill_candidate_claim_eligible=true`. Raw Skill hard-negative abstention and
final Skill injection remain ineligible and must not appear as positive
claims.

## Resume and reliability boundary

This track supports report rebuild from completed Case Records. It does not
implement mid-Turn resume, a durable attempt journal, crash recovery, or
external side-effect deduplication. Those remain outside PicoBench Ship-1.
