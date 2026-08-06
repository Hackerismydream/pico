# Runtime scheduler experiments

The Runtime scheduler benchmark isolates three claims that cannot be supported
by the original dispatch-overhead probe alone. It uses deterministic local
workloads so Provider and network variance cannot dominate queueing behavior.
The results are scheduler evidence, not a production service-level objective.

Run the frozen defaults from a clean checkout:

```bash
make picobench-runtime-scheduler
```

The command writes immutable evidence under
`.pico/evidence/picobench-runtime-scheduler/`. Generated evidence remains
outside Git. A result is claim-eligible only when every correctness Gate passes
and the commit, dependency lock, environment identity, and clean worktree stay
stable for the full run.

## Experiment 1: session head-of-line isolation

The control is one strict global FIFO with a fixed worker limit and
per-session serialization. If the queue head belongs to an already-running
session, later sessions wait. The treatment is Pico's session Lane scheduler
with the same USER concurrency limit. Both arms receive the same ordered trace:
a long hot-session burst interleaved with short foreground Turns from other
sessions.

The primary metric is foreground P95 queue wait. Each paired repetition
alternates arm order. The reported improvement is the median of the paired P95
reductions, rather than a percentile calculated from pooled repetitions.

## Experiment 2: foreground and background bulkheads

The control maps USER, CRON, and SUBAGENT work to one shared semaphore. The
treatment uses independent USER and Runtime-origin pools. Both policies have
the same total nominal capacity and run the same idle and background-saturated
foreground trace.

The primary metric is the ratio of loaded foreground P95 queue wait to idle
foreground P95 queue wait. Reporting a ratio controls for host-level timing
differences between repetitions. Policy and load order alternate across paired
repetitions.

## Experiment 3: accepted-request fate accounting

The request-fate experiment repeats the existing R0 Runtime conformance track.
It exercises normal execution, queued and running cancellation, injection,
interrupt, shutdown, origin limits, and rejection after draining. It aggregates
all accepted requests and requires zero lost requests, unexpected duplicate
executions, unresolved Handles, lifecycle contradictions, and pool-limit
violations.

This is an in-process guarantee from scheduler acceptance to terminal Handle
resolution. It does not claim exactly-once execution across process crashes or
external side effects.

## Live Agent response experiment

The live extension keeps the head-of-line comparison but replaces scripted
delays with `AgentTurnRunner -> AgentLoop -> configured Provider` calls. Every
foreground prompt owns a unique marker. A Turn is measurable only when the
reply contains that marker, Provider usage is complete, no Tool is called, and
the Runtime reaches a terminal result.

The control and treatment receive the same prompts in the same order, use the
same Provider and model, and use a balanced alternating arm order across 20
paired repetitions. Each arm contains two consecutive Turns from one hot
conversation followed by 100 foreground conversations, for 4,080 real Agent
Turns in total. The primary metric is foreground accept-to-terminal P95
latency. The reported effect is the median paired P95 reduction with a
deterministic 10,000-resample bootstrap 95% confidence interval.

Every Turn is retained as a raw record with its submission index, conversation,
accept/start/terminal offsets, queue wait, execution time, end-to-end latency,
usage, invocation count, and Verifier failures. The result is eligible only if
all Turns pass their task Verifiers, the confidence interval lower bound is
positive, and every Provider, usage, budget, checkout, and performance Gate
passes. This is an adversarial head-of-line burst benchmark, not a production
traffic model or service-level objective.

Live execution is a separately approved paid action. First freeze the clean
commit, exact manifest, maximum request attempts, and CNY hard cap:

```bash
make picobench-runtime-live-plan
```

Then pass the exact approved manifest digest and amount:

```bash
PICO_LIVE_PERF_APPROVAL_DIGEST=<digest> \
PICO_LIVE_PERF_APPROVED_CNY=<amount> \
make picobench-runtime-live-run
```

Rebuild the summaries and confidence interval from the retained raw Turn
records without calling the Provider:

```bash
PICO_LIVE_PERF_EVIDENCE=<run-artifact.json> \
make picobench-runtime-live-verify
```
