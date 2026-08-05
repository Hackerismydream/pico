# Small real Evolution Run: the disposable subject and its run protocol

> Status: current
> Owners: Evolver (`pico/evolver/`, `benchmarks/evolver/`)

The Evolution Run loop had been exercised by unit tests, fake benches, and the
AppWorld line, which needs an AppWorld install and a long budget. This spec
defines the small alternative: a disposable subject repo with three seeded
defects, its own bench plugin, and a one-round funnel that a real model can
finish in minutes. It is the cheapest honest end-to-end exercise of
`pico evolve check | run | status | finalize`.

The plugin contract itself is [`evolve-bench-contract.md`](evolve-bench-contract.md);
the methodology is [`self-evolution-loop-sop.md`](self-evolution-loop-sop.md).
This document covers only what the small-real subject adds: its layout, the
constraints its shape is forced into, the grading model, and the run protocol.

## Evidence boundaries

Three kinds of result come out of this slice, and none of them substitutes for
another:

| Class | Produced by | Claim |
| --- | --- | --- |
| Deterministic | `tests/test_evolver_small_real_bench.py`, run by `make verify-evolver` | The subject, the grader, the G5 binding, and one scripted funnel round behave as specified, offline |
| Live | `pico evolve run --config benchmarks/evolver/small_real.yaml` against a real model | One real Evolution Run reached a verdict on this subject |
| Provider failure | the design model refusing, or failing to answer with one usable module after its retries | The Provider failed, not the loop |
| Infrastructure failure | grading that could not be measured (see the infra marker below) | The measurement failed, not the candidate |

The deterministic gate scripts the design response, so it proves the loop's
mechanics and never proves that any model can repair the module. A live run
proves the opposite pair. A report that presents the deterministic round as a
run result, or a provider failure as a rejected candidate, is wrong on both
counts.

## Subject template layout

`scripts/setup_small_real_subject.py` copies `benchmarks/evolver/subject_template/`
to `benchmarks/evolver/subject/` (gitignored) and makes one commit with a pinned
identity and date, so every operator starts from the same root sha.

```
benchmarks/evolver/subject_template/
├── .gitignore                       __pycache__ (see "Why the subject stays clean")
└── benchmarks/appworld/
    ├── agent_cli.py                 THE mutable surface: slugify / parse_duration
    │                                / normalize_number, three seeded defects
    └── evolve/
        ├── tasks.py                 10 train + 4 sealed-test assertion tasks,
        │                            one WHY class per defect
        ├── grade.py                 stdlib-only scorer, run as a script in a
        │                            fresh interpreter; writes one result file
        │                            per trial with an infra marker
        ├── adapter.py               scorer driver + result readers (TaskEval,
        │                            KEPT ladder, design failure evidence)
        ├── candidate.py             Candidate + the G5 pre-commit manifest
        ├── designer.py              one-fenced-block design call and its parser
        └── entry.py                 build(ctx) -> BenchBundle
```

The three defects and the tasks that observe them:

| WHY class | Defect in `agent_cli.py` | Failing train tasks | Failing sealed tasks |
| --- | --- | --- | --- |
| `slug_separator_collapse` | `slugify` emits one separator per non-alphanumeric character and trims none | `slug-trim`, `slug-collapse` | `sealed-slug-punctuation` |
| `duration_hour_unit` | `parse_duration` knows `s` and `m` only, so hours contribute nothing | `duration-hours`, `duration-mixed` | `sealed-duration-hour-seconds` |
| `number_group_separator` | `normalize_number` keeps digit-group commas, so a grouped number falls to `0.0` | `number-grouped`, `number-grouped-int` | `sealed-number-currency-grouped` |

Vanilla therefore scores 4/10 on train and 1/4 on the sealed test, exactly and
repeatably: the module is deterministic stdlib text handling, so a K-trial
measurement measures the code and nothing else. Both numbers are asserted in
`tests/test_evolver_small_real_bench.py`.

## The G5 mutable-surface constraint

The subject module sits at `benchmarks/appworld/agent_cli.py` because that path
is a hard contract, not a naming preference. `pico.evolver.candidate_manifest`
ships one supported Candidate Label, `runtime`, whose `LabelPolicy.mutable_paths`
is exactly:

```python
mutable_paths=(
    "benchmarks/appworld/agent_cli.py",
    "benchmarks/appworld/tool.py",
),
```

G5 (`assert_manifest_gate`) runs *before* the candidate commit exists. A subject
module at any other path would make every candidate fail G5 with no commit to
inspect, so the disposable subject mirrors the allowlisted path.

The bench narrows that surface further. `entry.py` declares
`WHITELIST = ("benchmarks/appworld/agent_cli.py",)`, and `candidate.py` refuses
any other target before the manifest is built, so `tool.py` is inside the label
policy but outside this subject's surface. Both refusals raise `ManifestGateError`
before any child commit exists, which the loop records as a reproducible
`rejected_at_manifest` outcome; the deterministic gate asserts the subject's
commit count is unchanged after a rejection.

`validate_whitelist` runs at build time and refuses to start when a whitelist
entry matches no file at `base_sha` - a dead prefix would silently drop every
designer edit and burn a whole run on empty candidates.

## The gate policy is not a preference

`entry.py` must wire `FocusedFisherGate(k=k_confirm)`. Any other gate policy
turns a promoted candidate into a `failed` evidence record at the evidence hook.

The reason is a single required stat. `FocusedFisherGate` records the full-train
lift on the outcome
(`pico/evolver/orchestrator/gates/strategies.py`):

```python
lift = cand_mean - ctx.baseline.mean
stats["full_lift"] = lift
```

and the accepted-runtime evaluator bound to the `runtime` label
(`appworld_focused_fisher_v1` in `pico/evolver/candidate_evidence.py`) rebuilds
the verdict from canonical measurements and demands that the outcome reported
the same number:

```python
reported_lift = (outcome.stats or {}).get("full_lift")
if (
    not isinstance(reported_lift, (int, float))
    or not math.isfinite(float(reported_lift))
    or not math.isclose(float(reported_lift), full_lift, rel_tol=0.0, abs_tol=1e-12)
):
    raise CandidateEvidenceError("accepted runtime full-train lift does not match canonical measurements")
```

`PairedTwoSigmaGate` never sets `full_lift`, so under it every accepted
candidate raises here and is recorded as evidence-failed. The deterministic gate
pins the wiring by asserting `outcome.stats["full_lift"] == 0.6` on the scripted
round (10/10 candidate vs 4/10 vanilla).

## Grading model

`adapter.score_trials` never checks a candidate out as a working tree. It reads
the one declared mutable file out of the candidate commit with `git show`, drops
that copy into a throwaway directory, and grades it there with `grade.py` in a
fresh interpreter. Three consequences:

- a candidate cannot influence its own measurement through any file other than
  the one its manifest declares;
- the live subject checkout is never written to during a run (`HEAD` and
  `git status` are unchanged afterwards, asserted deterministically);
- `grade.py` is always the copy in the live checkout, never a version taken from
  the candidate commit, so the judge is fixed for the whole run. The evolver
  immutable kernel forbids candidates from touching `evolve/` anyway;
- before import, the fixed grader rejects imports (apart from future
  annotations), private-attribute access, namespace mutation, and dynamic-code
  or I/O builtins. A candidate therefore cannot patch the grader through
  `__main__` or reach filesystem, process, or network APIs. Policy rejection is
  a candidate failure, and the grading timeout still catches non-terminating
  allowed code.

### Result files and the infra marker

One JSON file per trial, `<out_dir>/<task_id>_k<k>.json`, written atomically,
carrying `success` and `infra_error`. The marker is what separates "the code
failed" from "the measurement failed":

| Situation | `success` | `infra_error` | Counted as |
| --- | --- | --- | --- |
| Cases ran, at least one mismatched | `false` | `null` | Task failure (the candidate's) |
| Candidate module raises or fails to import | `false` | `null` | Task failure |
| Module unreadable at the candidate sha | `false` | reason | Infrastructure failure |
| Grading process exited non-zero, or wrote no file | `false` | reason | Infrastructure failure |
| Grading process exceeded `bench_config.timeout` | `false` | `null` | Task failure |

The timeout row is the one deliberate judgement call. The subject module is
deterministic stdlib text handling with no I/O, so a grading timeout means the
candidate hangs. Marking it infrastructure would feed it into the infra-rerun
ladder forever and turn one bad candidate into an unmeasurable run; it is a
candidate failure and the code says so at the call site.

`read_out_dir` aggregates a directory into `TaskEval(passes, attempts,
infra_attempts)`; `read_kept_out_dir` applies the same KEPT rule as
`eval_with_infra_rerun` across the `_infra_rerun1` / `_infra_rerun2` siblings, so
the control arm read back from disk is the measurement the candidate arm was
scored against.

### Resume granularity

A complete, non-infra result file means that trial is done and is never
recomputed; an infra-marked or unparseable file is re-run. That is the whole
resume model: artifacts are the state, so an interrupted run continues by
re-invoking the same command. The deterministic gate proves it by poking a
marker key into a finished result file and an `infra_error` into another, then
re-scoring: the first survives untouched, the second is recomputed.

### Why the subject stays clean

The launcher imports the bench plugin out of the subject checkout
(`load_bench` puts the subject root first on `sys.path`), which makes CPython
write `__pycache__` next to the source. The setup script's dirty check is
`git status --porcelain -uall`, so without the template's `.gitignore` the
subject would count as dirty after the first `check` and the documented
`--reuse` step would be refused for the rest of the run.

## Run protocol

Everything below is deliberate: each step exists because it exercises a
guarantee the loop claims.

```bash
# 1. Materialize the subject (once). Reruns are explicit:
#    missing -> created; clean + --reuse -> kept; clean + --recreate -> rebuilt
#    (same root sha); clean with no flag -> exit 2; dirty -> exit 1, always.
#    --recreate additionally requires an exact current-template checkout and
#    refuses ignored paths, so it cannot delete an arbitrary clean Git repo.
uv run python scripts/setup_small_real_subject.py

# 2. Cheap pre-flight: config, models, bench bundle, whitelist, and the bench
#    precheck (a one-task grading probe). Nothing is spent yet.
uv run pico evolve check --config benchmarks/evolver/small_real.yaml

# 3. Optional isolated rehearsal. --smoke shrinks the funnel, pins the three
#    slugify tasks plus one sealed id, and suffixes work_dir with _smoke, so it
#    never touches the real run's state.
uv run pico evolve run --config benchmarks/evolver/small_real.yaml --smoke

# 4. The run. Send ONE SIGINT after cold start finishes to exercise resume:
#    the process exits 130 with the summary refreshed and completed trials kept.
uv run pico evolve run --config benchmarks/evolver/small_real.yaml

# 5. Resume: the same command, unchanged. Completed trials and journaled rounds
#    are not re-run.
uv run pico evolve run --config benchmarks/evolver/small_real.yaml

# 6. Status, twice: deterministic, read-only, and it never prints test numbers
#    while the run is unsealed.
uv run pico evolve status --config benchmarks/evolver/small_real.yaml
uv run pico evolve status --config benchmarks/evolver/small_real.yaml

# 7. Finalize, twice. The first unseals and writes retention.json; the second
#    reports the existing stamp and rewrites the same evolution_summary.json.
uv run pico evolve finalize --config benchmarks/evolver/small_real.yaml --yes
uv run pico evolve finalize --config benchmarks/evolver/small_real.yaml --yes
```

The run spec (`benchmarks/evolver/small_real.yaml`) pins one round:
`k_screen: 1`, `k_confirm: 2`, budget `1 WHY x 1 candidate`, `patience: 1`,
`max_rounds: 1`. `models:` is omitted, so every loop role uses Pico's own
configured model. `work_dir` is `.pico/evolver/small-real`, outside the subject
repo and under the gitignored evidence root.

### What the operator checks afterwards

| Claim | Where to look |
| --- | --- |
| Cold start is complete and resumable | `.pico/evolver/small-real/runs/vanilla/` holds 20 result files (10 train x K=2) |
| Rounds are journaled | `journal/rounds.jsonl`, one record per completed round |
| The summary is deterministic | `sha256` of `evolution_summary.json` is identical across both `finalize` calls |
| The sealed test was scored once, at the end | `retention.json` exists and `run_meta` carries the unseal stamp |
| An accepted candidate is reversible | `activation/<candidate_id>/rollback.json` is byte-identical to `before.json`, and the record's state is `pending_human` (the `runtime` label's activation policy is human review) |
| The subject was never mutated in place | `git -C benchmarks/evolver/subject status --porcelain` is empty and `HEAD` is still the root commit; candidate commits live under `refs/evolver/*` |

## Verdict semantics

A finished run reports one of these, and all of them are legitimate outcomes of
the exercise:

| Result | Meaning |
| --- | --- |
| `accepted` | A candidate passed the three-shield gate on full train and was promoted; activation artifacts exist and await human review |
| `rejected` | A candidate was measured and did not clear the bar (pruned at screen or at confirm), or was refused by G5 before a commit existed (`rejected_at_manifest`) |
| No improvement | Rounds completed, nothing beat vanilla; the loop stops with `patience_exhausted` or `max_rounds` |

These are product results. The next two are not, and must never be reported as
one:

| Non-result | Signature |
| --- | --- |
| Provider failure | the design model refused or never produced one usable fenced module within its retries; the round is recorded errored and repeated failures stop the loop with `errors_exhausted` |
| Infrastructure failure | trials carry an `infra_error` after the rerun ladder; evidence outcome is `failed`, and `status` prints the integrity error count |

Evidence outcomes on disk use the same four names everywhere
(`accepted` / `rejected` / `failed` / `inconclusive`); `status` prints their
counts from `evolution_summary.json`. A `failed` or `inconclusive` candidate
never promotes and never enters the elite archive.

## Deterministic gate

`tests/test_evolver_small_real_bench.py` is the offline half of this slice and
runs inside `make verify-evolver`. It covers the setup script (determinism,
rerun modes, dirty and foreign refusals, destructive-recreate guard), the design
parser edges (no block, two blocks, empty, oversized, non-Python, missing public
names), the grader on the seeded defects (vanilla, a corrected module, resume,
infra marking, harness-tampering rejection), the G5 surface pin, model-free
orchestrator reconstruction for `finalize`, and one complete round driven by a
scripted design response that ends `accepted` with a byte-equal rollback
bundle.

The subject's bench plugin shares its import path (`benchmarks.appworld`) with
the host repo's real AppWorld plugin. The production registry sees that this
subject owns the registered entry, puts its root first on `sys.path`, evicts a
cached `benchmarks` package when it came from another root, then verifies that
the imported entry belongs to the requested subject. Legacy subjects without
their own entry still use Pico's host plugin. The test fixture additionally
restores the host modules afterwards, so the subject's copy cannot leak into
AppWorld tests that run later in the same process. Any new test touching the
subject must reuse that fixture.

### Rerun

```bash
uv run pytest tests/test_evolver_small_real_bench.py -q
make verify-evolver
```

## Maintenance

- Changing the subject template changes the subject root sha. Nothing may
  hardcode that sha; the deterministic gate asserts only that two
  materializations agree.
- Adding a task to the subject changes the vanilla scores asserted in the
  deterministic gate; update both in the same change.
- The gate policy pin is load-bearing. If `entry.py` ever moves off
  `FocusedFisherGate`, the `runtime` label needs a new evaluator binding first.
