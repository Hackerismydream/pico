# V-R0: the release candidate Gate

V-R0 is the last Gate in the catalog. It does not add a new claim about Pico;
it assembles the claims the other Gates already make into one report bound to
one commit, and it names every layer that is missing instead of quietly
dropping it.

Driver: [`scripts/verify_release.py`](../../scripts/verify_release.py).
Entry point: `make verify-release`.
Report: `.pico/evidence/release/release-report.json`, schema
`pico.release.evidence.v1`.

## Why a driver instead of a checklist

Every earlier Gate writes its own evidence, and each one is honest about its
own scope. What no single Gate can answer is the release question: did all of
them pass, at the same commit, on the same machine, in one run. A checklist
answers it by hand, and a hand-assembled release is exactly where evidence
from an older branch, an older wheel, or an older PR gets reused because it
looked green at the time.

The driver removes that discretion. It runs the layers itself, records what
each command actually did, imports a sub-report only when that report belongs
to the commit under test, and refuses to call the run passed while anything is
unaccounted for.

## Layers

Layers run in this order. The order is a dependency order: V-P0 produces the
wheel the host, live-provider, and Evolution Run layers consume.

| Layer | Gate | Command | Evidence class |
| --- | --- | --- | --- |
| `v_d0` | V-D0 | `make test-retained` | deterministic |
| `v_t0` | V-T0 | `make lint-tui test-tui build-tui` | deterministic |
| `v_p0` | V-P0 | `scripts/verify_distribution.py` into a fresh temp root | package |
| `host_gate` | host gate | `make verify-runtime-hosts` with `PICO_WHEEL` from the V-P0 handoff | package |
| `v_lp` | V-LP | `make verify-live-provider` | live |
| `v_c0_s0` | V-C0 / V-S0 | `make verify-channels` | deterministic |
| `v_lf` | V-LF | `make verify-live-feishu` | live |
| `memory_continuity` | CodeCairn M2/M4 | currently unwired; `run_memory_continuity` still returns an inconclusive legacy gap | package |
| `v_te0` | V-TE0 | `make verify-turn-evidence` | deterministic |
| `v_e0` | V-E0 | `make verify-evolver` | deterministic |
| `deps_audit` | dependency audit | `pip-audit` plus `npm audit` with and without dev dependencies | audit |
| `assets` | asset gate | `make check-large-files` | deterministic |
| `evolution` | small real Evolution Run | `pico evolve check/run/interrupt/run/status/finalize` from the installed wheel | live |

`v_te0` and `v_e0` spend no live model calls and stay deterministic. The
historical EverOS V-O0 layer was removed with that product integration.
`memory_continuity` records
`codecairn_joint_evidence_not_authorized = inconclusive` instead of silently
dropping the release requirement. Issue #70 has now completed the standalone
CodeCairn joint Gate, but V-R0 has not yet been wired to execute and bind that
Gate. The gap name is therefore a stale implementation label, not the current
authority state. V-R0 cannot pass until the driver and its tests consume the
completed verifier and current-commit report.

## Per-layer record

Each layer contributes one record:

| Field | Meaning |
| --- | --- |
| `layer`, `gate` | The layer id and the Gate label it stands for |
| `command` | Every command the layer ran, in order, with the executable resolved to an absolute path |
| `exit_code` | The exit code that decided the layer: the first non-zero, otherwise 0 |
| `status` | `passed`, `failed`, `skipped`, `inconclusive`, `provider_failure`, or `infrastructure_failure` |
| `log`, `log_sha256` | The layer log under `<output-root>/logs/` and its digest |
| `report_path`, `report_sha256` | The sub-report the layer imported or produced, when it has one |
| `evidence_class` | `deterministic`, `package`, `live`, or `audit` |
| `gaps` | The named gaps this layer contributed |

A timeout, a missing executable, or a spawn error is `infrastructure_failure`,
never a product failure. A non-zero exit is `failed` unless the layer output
names `provider_failure`, `infrastructure_failure`, or `inconclusive`, in which
case that classification is kept.

## Commit binding

The driver reads `git rev-parse HEAD` once and binds the whole run to it. Two
rules follow, and both are refusals rather than warnings:

1. A sub-report that records a commit (`source_sha`, `commit`, or
   `source.commit`) must record this commit. A different commit produces the
   gap `report_stale_commit`.
2. A sub-report file older than the layer that claims it belongs to an earlier
   run: gap `report_stale_artifact`. This is what stops a Gate that failed
   before writing its report from inheriting the previous run's green file out
   of `.pico/evidence/`.

A layer whose command exited 0 but whose report is missing, unreadable, stale
by commit, or stale by artifact is downgraded to `failed`. It claimed a pass it
cannot bind to this commit, and an unbindable pass is worth less than an honest
failure.

The checkout itself is bound the same way: uncommitted changes produce the
run-level gap `worktree_dirty`, because release evidence describes a commit and
a dirty tree is not one.

## Named gaps

Gaps are the vocabulary for everything the run could not measure. Each entry
carries the layer, the gap name, and a detail string.

| Gap | Raised when |
| --- | --- |
| `layer_not_run` | A `--layers` subset left the layer out |
| `worktree_dirty` | The checkout has uncommitted changes |
| `report_missing`, `report_stale_commit`, `report_stale_artifact` | The layer could not bind its sub-report |
| `live_provider_credentials_missing` | `PICO_LIVE_API_KEY` is absent |
| `feishu_credentials_missing` | Any `PICO_LIVE_FEISHU_*` variable or `PICO_LIVE_API_KEY` is absent |
| `distribution_handoff_missing` | V-P0 did not hand off a verified wheel |
| `codecairn_joint_evidence_not_authorized` | Legacy gap currently emitted because V-R0 has not yet been wired to the completed CodeCairn continuity Gate |
| `small_real_files_missing` | The small real Evolution Run inputs are absent |
| `evolution_interrupt_not_observed` | The Evolution Run exited before the interrupt, leaving resume unproven |
| `dependency_finding_blocking` | A dependency finding the ledger does not waive |
| `dependency_audit_unreadable`, `exception_ledger_unreadable` | An audit or the ledger produced nothing parseable |

Missing live credentials fail their layer rather than marking it inconclusive:
V-LP and V-LF are required layers, the harness is runnable, and only the
operator's credentials are missing. Missing inputs that do not exist in the
checkout at all - the V-P0 handoff, the small real Evolution Run files - are
`inconclusive`, because nothing was measured and nothing failed.

## Status

Overall status is `passed` only when the run selected every layer, named no
gap, and every layer passed. Current `main` cannot reach that state because the
explicit `memory_continuity` placeholder remains inconclusive even though
`codecairn-003` is complete; the driver has not yet been wired to the new Gate.
Otherwise the most severe layer status wins, in
the order `failed`, `provider_failure`, `infrastructure_failure`,
`inconclusive`; a run that is not release-eligible and has nothing more severe
than skips is `failed`.

`--layers` exists for development reruns. A subset run writes the same report,
records the layers it did not run as `skipped` with a `layer_not_run` gap, and
can never report `passed`. There is no flag that relaxes this.

## Dependency audit

The layer runs three commands and reconciles their findings against
[`docs/baselines/exception-ledger.toml`](../baselines/exception-ledger.toml):

- `python -m pip_audit -f json --desc off --aliases on --progress-spinner off`
- `npm audit --prefix ui-tui --json`
- `npm audit --prefix ui-tui --omit=dev --json`

The production surface is what `--omit=dev` reports; anything only the full
audit sees is development-only. pip-audit reports no severity, so every Python
finding is treated as potentially blocking rather than assumed low.

Reconciliation, per finding:

| Disposition | Meaning |
| --- | --- |
| `below_release_threshold` | Severity is known and below high |
| `policy_blocked` | Critical or high on the production surface; `release_blocks_critical_or_high` in the ledger makes it unwaivable |
| `transitive` | The package carries no advisory of its own and inherits one from another reported package, which is where the block lands |
| `ledgered` | An active `temporary-reachability-exception` covers it |
| `ledger_entry_closed` | A ledger entry matches, but it is remediated, resolved by removal, or expires before V-R0 |
| `unledgered` | No ledger entry matches |

npm repeats one advisory across every dependent of the affected package, so a
dependent is attributed to its root instead of demanding a ledger entry of its
own. The attribution only applies when the root appears in the same audit; a
dependent whose root is not reported blocks on its own.

An entry whose `expiry` is `before-v-r0` cannot waive a finding inside a V-R0
run. Honoring it there would silence exactly the advisory the entry asked to
re-evaluate at release time. The reconciliation result is written to
`<output-root>/dependency-audit.json` and hashed into the layer record.

## The small real Evolution Run layer

The `evolution` layer consumes a contract owned by a separate change:

- `scripts/setup_small_real_subject.py` prepares the subject repository
- `benchmarks/evolver/small_real.yaml` is the run spec

Given both, the layer runs, from the entrypoint installed by V-P0:

1. `pico evolve check --config benchmarks/evolver/small_real.yaml`
2. `pico evolve run --config ...`, interrupted with SIGINT once it is running
3. `pico evolve run --config ...` again, resuming the same journal
4. `pico evolve status --config ...`
5. `pico evolve finalize --config ... --yes`

The interrupt is the point of the layer: it is the only place in the catalog
where a real Evolution Run is proven to survive a process death and resume from
its journal. If the run finishes before the interrupt deadline, the layer is
`inconclusive` with `evolution_interrupt_not_observed` rather than passed on a
weaker claim. While the two input files are absent, the layer reports
`small_real_files_missing`.

## What V-R0 does not do

- It does not re-verify what a layer already verified. A layer's report is
  imported, not re-derived.
- It does not accept evidence from another commit, another branch, another PR,
  or another machine. Artifacts attached to an older pull request are not
  substitutes, however green they were: the whole point of the driver is that
  the layers passed together, here, now.
- It does not tag or publish. The tag-triggered workflow in
  `.github/workflows/release.yml` stays draft until a full V-R0 pass exists;
  this change does not modify it.
- It does not make the Evolver, the Channels, or the live Providers more mature
  than their own Gates claim. V-R0 reports their results, it does not upgrade
  them.

## Self-coverage

The driver's pure functions - selection, classification, commit binding, gap
aggregation, status, and dependency reconciliation - are tested in
`tests/test_verify_release.py` with every subprocess call monkeypatched. Those
tests run inside `make test-retained`, which is the `v_d0` layer, so a V-R0 run
carries evidence that its own driver still behaves.
