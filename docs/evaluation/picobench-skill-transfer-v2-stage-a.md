# PicoBench Skill Transfer V2 Stage A

Stage A tested whether useful learning-side knowledge can improve held-out
repository tasks before investing in a new automatic Myna compiler. It used the
same 24 held-out tasks as V1, two repetitions, and three arms:

- no Skill;
- the frozen V1 long Skill with deterministic ability routing; and
- a compact Anchor written only from the three learning examples for that
  ability, with the same deterministic routing.

All Skill arms still passed through Pico's exact-ID Gate. The oracle selector
was credential-free, so only main-Agent calls were charged.

## Result

The run completed 144/144 Trials with valid budget and verification receipts:

| Arm | Verified passes | Rate |
|---|---:|---:|
| No Skill | 30/48 | 62.50% |
| V1 long Skill | 26/48 | 54.17% |
| Compact Anchor | 30/48 | 62.50% |

The preregistered primary contrast, Anchor minus No Skill, was `0.00` percentage
points with a task-clustered 95% interval of `[-18.75, 18.75]`. There were eight
paired gains and eight paired regressions. The long Skill contrast was `-8.33`
points with interval `[-18.75, 2.08]`, with three gains and seven regressions.

The JSONL family passed 0/8 in both No Skill and Anchor, so the report marks it
as a capability floor for this model and Tool budget. Total Provider cost was
CNY 3.43071855 under the frozen CNY 3.50 cap, with zero open reservations.

## Decision

Stage A did not satisfy the frozen continuation rule: the Anchor contrast's
confidence-interval lower bound was not above zero. Stage B, Stage C, and the
Myna v2 compact compiler are therefore not executed on this task/model setup.

This is a causal stop, not a claim that Skill learning can never work. The
experiment shows that even learning-only compact content with perfect ability
routing did not improve this benchmark under the chosen model and execution
budget. The V1 long content remained harmful, while selection errors were
removed from the Stage A contrast.
