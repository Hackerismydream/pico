# PicoBench `skill_transfer_v1`

## Claim under test

For the frozen six-ability coding pack, does activating an instruction-only
Skill derived from three verified, instance-disjoint learning Experiences
increase independently verified held-out task success without causing a
hard-negative injection or a paired regression?

This is narrower than “the Agent improves itself in general.” It isolates one
causal axis: both arms have the same Pico Runtime, Myna Capture, verified
learning Experiences, Provider, model, prompt, Tools, budgets, and repository
fixture. The Control keeps the derived revision unavailable. The Treatment
activates that exact revision.

## Frozen matrix

| Item | Count |
|---|---:|
| Ability families | 6 |
| Learning instances per family | 3 |
| Learning instances total | 18 |
| Held-out instances per family | 4 |
| Held-out instances total | 24 |
| Repetitions per arm | 2 |
| Paired comparisons | 48 |
| Primary Trials | 96 |
| Hard-negative queries | 24 |

The ability families cover configuration precedence, bounded Retry-After
handling, atomic JSON replacement, JSONL identity deduplication, resolved-path
containment, and exception-safe asynchronous cleanup. Learning, held-out, and
hard-negative identities are globally disjoint in the checked-in corpus.

## Candidate and budget

The current frozen plan binds:

- Pico commit `6ad559b62cc3ab651d96e517f43041cd5a04524b`;
- Pico wheel SHA-256
  `0e19c558c388cc912e779f16278866f3ede7070aea6655fcde1b4af6e2d9810e`;
- Myna commit `1167e319f0c9e5c3654fd27c08e99d3ca95a260d`;
- Myna wheel SHA-256
  `6c4ceed194ebf2c5ed28230232c2c16b571024ead2e799601884ffd04bf03a5f`;
- DeepSeek V4 Flash through the frozen Pico Provider adapter;
- approval digest
  `35a7a678b478328f2a830a7ef014be0e6e2b7800795d9b92e5ef36bed0d90fd6`;
- worst-case budget CNY 22.527590 under a CNY 25 hard cap.

The six Skill-extraction calls and all evaluation-Agent calls share one durable
Provider budget ledger. The run command rejects a missing credential, missing
paid-execution flag, mismatched approval digest, insufficient approval, or an
approval above the hard cap.

## Positive-claim gate

A positive result requires all of the following:

1. 48/48 complete, valid Pairs and 96 exact primary Trial records;
2. no learning/held-out/hard-negative identity overlap;
   the candidate subprocess receives only the digest-bound learning projection;
3. Treatment injection of the exact accepted revision and no Control
   injection;
4. a one-to-one learning-instance-to-Experience map, three source Experience
   identities, and three frozen learning identities for every active revision;
5. valid independent task-verification receipts and unchanged public smoke
   fixtures;
6. 24/24 hard-negative records with zero recalled Skill revisions;
7. no Pair where Control passes and Treatment fails;
8. complete Turn, Tool-call, latency, input-token, output-token,
   Provider-call, and conservative cost records;
9. a held-out-instance-clustered 95 percent bootstrap interval whose lower
   bound for paired pass delta is greater than zero; and
10. directory-digest binding of the exact Control and Treatment candidate
    runtime snapshots; and
11. an `inventory.json` binding every raw, budget, candidate, and derived
    evidence artifact by SHA-256; and
12. offline reproduction of aggregate, verifier report, claim object, and
    Provider budget state from immutable raw records.

Provider, transport, budget, or infrastructure failures invalidate a Pair.
They are not converted into task failures. Skill injection alone is mechanism
evidence, not task-effect evidence.

## Current evidence status

As of 2026-08-25:

- the exact-wheel installed mechanism gate passes draft generation, activation,
  prompt injection, hard-negative abstention, successor generation,
  Supersession, rollback, rejection, denied reactivation, and restart recovery;
- the full Pico check passes 4,006 Python tests and 830 TUI tests;
- the full Myna check passes 584 Python tests, 53 Hub tests, and its integration
  checks; and
- the paid 96-Trial campaign has **not run**. Therefore there is no current
  positive task-effect claim and no improvement percentage to quote.

The deterministic installed gate uses a local TLS fixture Provider. It proves
the product mechanism and governance wiring, not semantic-model quality. The
formal campaign uses the frozen live Provider and remains gated on explicit
budget authorization.

## Commands

Plan without Provider calls:

```bash
make picobench-skill-transfer-plan
```

Run only after exact approval:

```bash
PICO_BENCH_EXECUTE_PAID=1 \
PICO_SKILL_TRANSFER_APPROVAL_DIGEST=<digest> \
PICO_SKILL_TRANSFER_APPROVED_CNY=<approved-cny> \
make picobench-skill-transfer-run
```

Offline rebuild without Provider calls:

```bash
make picobench-skill-transfer-verify
```
