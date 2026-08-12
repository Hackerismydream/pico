# PicoBench Myna task-effect v1

> **Status: implemented credential-free installed-candidate experiment.** The
> deterministic Agent policy is a Runtime and Memory lifecycle calibration. It
> can support a frozen-workload efficiency claim, but it is not evidence that a
> general-purpose model improves on arbitrary repositories.

The lightweight real-Agent subtrack below is the task-effect benchmark. It
keeps this deterministic track as lifecycle calibration instead of relabeling
its mechanically constrained repository-read result as general Agent uplift.

## Lightweight real-Agent subtrack

The `agent` corpus adds 12 cross-Session scenarios, with three tasks in each of
the same four risk classes. It runs two balanced repetitions of the Memory-off
and Myna arms: 24 Pairs and 48 evaluation Trials in total. The prior experience
Turn is setup, not a scored Trial.

The only treatment remains `memory.backend = null` versus
`memory.backend = myna`. Both arms otherwise freeze the installed Pico and Myna
wheels, configured Provider and model, task, prompt, Tools, context budget, Tool
iteration budget, timeout, and external Verifier. The campaign is frozen to
`deepseek/deepseek-v4-flash` so model drift cannot silently change the Pack.

Primary metrics are externally verified task pass rate, Tool Calls among Pairs
where both arms pass, and Provider input tokens among Pairs where both arms
pass. The efficiency Gate requires task-pass non-inferiority within five
percentage points, at least 80%
concordant passing Pair coverage, at least 15% Tool Call reduction, at least 10%
input token reduction, and task-clustered bootstrap intervals above zero for
both efficiency metrics. A capability claim separately requires at least a
10-percentage-point pass-rate gain with its interval above zero. Any stale
Memory-caused regression or cross-repository Memory event blocks every positive
claim.

Planning writes no Trial and makes no Provider call. The run command requires
the frozen manifest digest, an approved CNY amount covering the worst case
without crossing the CNY 10 hard cap, and `PICO_BENCH_EXECUTE_PAID=1`. The
default plan is 48 evaluation Trials, at most 480 Provider attempts, and a
conservative CNY 4.644864 worst-case estimate. Completed Trial records resume
rather than rerun. The offline verifier rebuilds metrics and checks the
append-only Provider budget ledger without a Provider call. Every passing raw
Trial also carries the observed JSON, artifact SHA-256, terminal outcome, and
unexpected-path inventory so task success is rebuilt rather than trusted as a
stored boolean.

Because 12 tasks are below the 30-task confirmatory threshold, bootstrap
intervals are explicitly exploratory. A passing Gate supports only a scoped
claim about this frozen lightweight Pack; `general_agent_claim_eligible`
remains false.

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

Plan the real-Agent subtrack after supplying the same exact candidate inputs:

```bash
make picobench-memory-agent-plan
```

Run it only after reviewing the printed digest and ceiling:

```bash
PICO_BENCH_EXECUTE_PAID=1 \
PICO_MEMORY_AGENT_APPROVAL_DIGEST=<printed-digest> \
PICO_MEMORY_AGENT_APPROVED_CNY=4.644864 \
  make picobench-memory-agent-run
```

Rebuild the accepted evidence without Provider calls:

```bash
make picobench-memory-agent-verify
```
