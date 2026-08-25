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

The completed candidate binds:

- Pico commit `51254981b9caaa5db5d5646efa612b2b16a58842`;
- Pico wheel SHA-256
  `0e19c558c388cc912e779f16278866f3ede7070aea6655fcde1b4af6e2d9810e`;
- Myna commit `13e605d606bffb802d1028dc45a1c15b4ca6137e`;
- Myna wheel SHA-256
  `75febd8fae7a985b8b0ece27cca308abfb9070a62031168550cc1b6c6386f2a0`;
- DeepSeek V4 Flash through the frozen Pico Provider adapter;
- approval digest
  `a63b81527dd305839b34b0a2f2e7ff98f94f3cacc3fef3c623e547532beb42c9`;
- worst-case budget CNY 21.495398 under a CNY 25 hard cap; and
- DeepSeek thinking disabled, a 32,768-token task-input ceiling, one task
  attempt per logical call, and two candidate-extraction attempts per call.

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

As of 2026-08-25, the formal campaign is complete:

- 48/48 Pairs and 96/96 primary Trials are complete and valid, with no Provider,
  transport, memory-backend, or other infrastructure failure;
- Control passes 32/48 and Treatment passes 25/48, for a verified pass delta of
  **-14.583333 percentage points**;
- the held-out-task-clustered 95 percent bootstrap interval is **[-31.25, 0]**;
- Treatment has 3 paired gains and 10 paired regressions;
- all 24 hard negatives complete with zero incorrect Skill injections;
- the exact Treatment revision is injected, Control remains unexposed, all 18
  learning-instance-to-Experience mappings are bound, and the 12 runtime
  snapshots remain digest-bound;
- the Provider ledger records 500 request attempts and CNY 2.16426315 charged;
  mean estimated Trial cost is CNY 0.020437 for Control and CNY 0.024379 for
  Treatment; and
- offline verification reproduces the aggregate, claim object, candidate
  bindings, budget state, verifier receipts, and SHA-256 artifact inventory.

The measurement is valid and ship-complete, but it is not positive-claim
eligible. The result rejects automatic activation for this candidate and
supports the existing receipt gate: reliable generation, Recall, and injection
do not by themselves imply task improvement.

The effect is heterogeneous. Asynchronous cleanup gains one net pass (6 versus
5), atomic JSON and configuration precedence are tied (6 versus 6 and 7 versus
7), JSONL deduplication is beyond this model-budget configuration (0 versus 0),
and the largest regressions occur in resolved-path containment (4 versus 8) and
Retry-After handling (2 versus 6). This points to selection and instruction
specificity as the next experimental axis, not broader automatic activation.

## Commands

Plan without Provider calls:

```bash
make picobench-skill-transfer-plan
```

Run the installed formal-runner preflight without external Provider calls:

```bash
make picobench-skill-transfer-preflight
```

Derive and inspect the frozen candidates before primary Trials:

```bash
PICO_BENCH_EXECUTE_PAID=1 \
PICO_SKILL_TRANSFER_APPROVAL_DIGEST=<digest> \
PICO_SKILL_TRANSFER_APPROVED_CNY=<approved-cny> \
make picobench-skill-transfer-prepare
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
