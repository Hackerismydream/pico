# PicoBench Myna task-effect v1

> **Status: implemented credential-free installed-candidate experiment.** The
> deterministic Agent policy is a Runtime and Memory lifecycle calibration. It
> can support a frozen-workload efficiency claim, but it is not evidence that a
> general-purpose model improves on arbitrary repositories.

## Question

The experiment asks whether Myna can reduce repository rediscovery work across
a real process and Session boundary without reducing externally verified task
success.

Every task remains independently solvable from repository evidence with Memory
disabled. Positive tasks make an earlier fact or execution experience available
through Myna. Stale and irrelevant tasks require the Agent policy to read the
current repository instead of trusting recalled text.

## Single treatment axis

```text
control:   memory.backend = null
treatment: memory.backend = myna
```

Each Pair freezes the same Pico wheel, Myna wheel, task, repository fixture,
prompt, deterministic Provider policy, Tools, context budget, Turn budget, and
Verifier. The treatment receives no additional Tool, token, retry, or timeout
allowance.

## Trial lifecycle

The treatment executes the installed public seam:

```text
prior Turn
  -> MemoryBackend.start
  -> Agent Loop after-Turn store
  -> process exit and MemoryBackend.stop
  -> fresh process and fresh Session
  -> MemoryBackend.start
  -> Context Memory recall
  -> evaluation Turn
  -> Agent Loop after-Turn store
  -> MemoryBackend.stop
```

The control executes the same prior and evaluation Turns with no Memory Backend
construction or lifecycle operation. Trial state and Myna runtime roots are
isolated. AB and BA order rotates from a frozen seed.

The deterministic Provider does not contain task answers. For fact and
experience tasks it uses a task-bound value only when that value appears in the
recalled Memory segment. Otherwise it reads the declared repository evidence.
It always reads current evidence for stale/conflict and irrelevant tasks. A
parent-owned Verifier checks the exact JSON artifact and rejects unexpected
workspace mutations.

## Frozen task sets

| Track | Tasks | Default repetitions | Trials |
| --- | ---: | ---: | ---: |
| Calibration | 6 | 2 | 24 |
| Formal | 24 | 3 | 144 |

The formal set contains six tasks in each class: repository fact, execution
experience, stale/conflict, and irrelevant. It spans four repository identities.
Calibration and formal identities are disjoint.

## Metrics and claims

The report keeps capability and efficiency claims separate.

- Capability: verified pass-rate Pair delta. Eligibility requires at least a
  10 percentage-point improvement and a task-clustered bootstrap 95% interval
  above zero.
- Efficiency: repository-read reduction among concordant passing Pairs.
  Eligibility requires pass-rate non-inferiority within five percentage points,
  at least 80% concordant-pair coverage, at least 20% mean read reduction, and a
  task-clustered bootstrap 95% interval above zero.
- Safety: stale Memory may not cause a regression and recalled metadata may not
  cross repository identity.

Myna startup, store, index, or Recall failure is retained as a treatment product
failure. It is not removed as Provider infrastructure. A control-side Myna
operation invalidates the treatment axis.

## Evidence

An accepted run contains:

```text
manifest.json
raw-outcomes.jsonl
aggregate.json
verifier-report.json
claim-eligibility.json
inventory.json
```

The manifest binds both full source commit declarations, both wheel SHA-256
digests, installed distribution versions, entry-point identity, corpus digest,
repetition count, and randomization seed. Raw Trial records are append-only;
rerunning the command resumes missing Trials and rebuilds all derived evidence.

`ship_complete`, `measurement_valid`, and `positive_claim_eligible` remain
independent. A positive efficiency result from this track must be described as a
deterministic installed-candidate result, not as general coding-task uplift.

## Commands

Set exact candidate inputs before any command:

```bash
export PICO_MYNA_PICO_WHEEL=/absolute/path/to/pico.whl
export PICO_MYNA_WHEEL=/absolute/path/to/myna.whl
export PICO_MYNA_PICO_COMMIT=<40-character-pico-sha>
export PICO_MYNA_COMMIT=<40-character-myna-sha>
```

Inspect calibration without executing a Trial:

```bash
make picobench-myna-task-effect-plan
```

Run or resume calibration:

```bash
make picobench-myna-task-effect-run
```

Run formal after calibration evidence is accepted:

```bash
PICO_MYNA_TASK_EFFECT_KIND=formal make picobench-myna-task-effect-run
```

The task Provider is local and makes no paid model calls. The first FastEmbed
prefetch may download the pinned local retrieval model. The manifest reports
paid Provider calls as zero; it does not mislabel unobserved network transfer as
a currency receipt.
