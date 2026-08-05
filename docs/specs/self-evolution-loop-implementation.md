# Self-evolution SOP <-> Pico implementation map

**Companion:** [`self-evolution-loop-sop.md`](self-evolution-loop-sop.md) — an
English translation of the methodology SOP. This document answers which code
implements each clause in Pico, which deviations are deliberate, and which
parts are present but unwired. The implementation lives under the
`pico/evolver/` namespace.

**How to use:** before changing `pico/evolver/**` or
`benchmarks/appworld/evolve/**`, locate the SOP clause here; if your
change alters a correspondence, update this document in the same PR.

---

## 0. The fundamental architectural difference (read first)

The SOP's loop (§3 / §8.3) is **Claude-driven**: no driver program — a human
opens Claude and walks the seven-step funnel by hand, state persists in three
file layers, and the parts are a set of CLI scripts. Pico implements the same
methodology as a **program-driven** loop:
`pico/evolver/orchestrator/loop.py::EvolutionOrchestrator` is a deterministic
driver for the funnel, and the SOP's CLI parts became functions embedded in
the loop.

The SOP §8.0 division of labor (semantics to the model, deterministic
arithmetic to code) is preserved unchanged: diagnosis / design / verdict are
still LLM calls, wrapped in `orchestrator/nodes/semantic.py::SemanticNode`
(parse failures are fed back for bounded repair retries). Only "who presses
the next-step button" changed.

The SOP itself (§8.3) judges this route: "packaging into one-click tools is a
large-benchmark task". Pico chose to build the integration now, buying
cross-window hand-off freedom and mechanized methodology (see §5, "Where we
exceed the SOP").

---

## 1. SOP §0 general rules -> implementation

| SOP clause | Pico implementation | Evidence (file :: symbol) |
|---|---|---|
| Gate0 pre-run environment health check | precheck injected per round, forced once before cold start | `orchestrator/production.py::build_evolution_orchestrator` (`run_gate0`); `benchmarks/appworld/evolve/precheck.py::make_appworld_precheck` |
| Infra-failure ladder: detect -> rerun <=2 -> score 0 if still broken | `eval_with_infra_rerun`, `max_reruns=2`, produces the `_infra_rerun{1,2}` directory ladder; the KEPT rule takes the measurement with the fewest infra trials | `orchestrator/scoring.py::eval_with_infra_rerun`; `benchmarks/appworld/evolve/adapter.py::ladder_out_dirs / read_kept_out_dir` |
| ★ Denominator = total tasks; infra tasks never excluded | Gate-f never shrinks the denominator. Persistent Provider or infrastructure failure produces a `failed` verdict and cannot promote; missing, zero-attempt, or fewer-than-requested-K evidence is `inconclusive` | `orchestrator/scoring.py::measurement_validity`; `orchestrator/gates/pipeline.py::run_gates` |
| Division of labor: semantics = model, determinism = code | see §0 above | `orchestrator/nodes/semantic.py::SemanticNode` |
| Navigation vs statistical credit | `PairedResult` keeps `promoted` and `credited_2sigma` separate, but both require a valid measured comparison; failed or inconclusive evidence earns neither | `orchestrator/gates/paired.py::PairedResult / paired_lift` |
| Paired σ: std of per-task paired diffs, removing between-task difficulty | `d_i = rate_c,i − rate_v,i`, `se = stdev(d)/√n`, `z = lift/se` | `orchestrator/gates/paired.py::paired_lift` |
| ★ Sealed test: blind-run each round, invisible to decisions, unseal at the end for retention | `SealedTestRunner.score` writes to a driver-invisible directory and **returns None** (no test number can physically enter the decision path); `unseal` only after the loop ends | `orchestrator/sealed/runner.py::SealedTestRunner / unseal_retention` |
| Test never enters anchor/train | stronger than the SOP's discipline: a mechanized assertion — leakage raises at startup | `orchestrator/sealed/runner.py::assert_no_test_leak`, wired in `loop.py` construction |
| Discipline: diagnose from train trajectories only | the diagnosis corpus source hangs off train only; test trajectories have no read path (the sealed runner stores scores only) | `orchestrator/scoring.py::EvalBackend.trajectories` |
| Discipline: configuration identical throughout | mechanized at the launcher level: `run_meta.json` records a config fingerprint; a changed config refuses to resume | `evolver/launch/state.py::RunMeta.check_config` |

## 2. SOP §1 cold start -> implementation

| SOP clause | Pico implementation | Evidence |
|---|---|---|
| Vanilla train full set x K=3 thick ledger | `backend.cold_start()` must return a non-empty stability ledger; baseline frozen-seeded from the vanilla out-dir | `orchestrator/loop.py` (construction); `benchmarks/appworld/evolve/run.py` (`seed_label="van0"`, `cold_start_k`) |
| Failure map covers >= 7 WHY classes | `diagnose_round(min_why_classes=7)` | `orchestrator/nodes/diagnose.py::diagnose_round` |
| WHY x WHERE taxonomy; inducible for a new bench | `TaxonomySpec` + two-stage `induce_taxonomy`; induction failure raises loudly, never silently borrowing another bench's table | `orchestrator/nodes/taxonomy.py` |

## 3. SOP §2 seven-step funnel -> implementation

| SOP step | Pico implementation | Evidence |
|---|---|---|
| ① Round 1 uses the cold-start map; round 2+ re-diagnoses the child (fired / flipped / still-failing), appending to the living map | `_diagnosed_parents` prevents duplicate diagnosis; `merge_failure_maps` accumulates cross-round and persists; flips recorded in `_flips` with a harm-replay excerpt (how the regressed task actually broke) | `orchestrator/loop.py` (round body); `orchestrator/production.py::outcome_hook` |
| ② 1-2 WHYs x 2-3 candidates, budget-capped; isolated activation | WHY selection defaults to driver mode (model picks; formula fallback + shadow log); `Budget(max_why_per_round x candidates_per_why)` is enforced in code. AppWorld uses commit-checkout activation: each candidate is a child commit evaluated from an ephemeral worktree, with Python execution attributed by a beacon. The SOP's env-gated mode remains a planned framework-line variant | `benchmarks/appworld/evolve/editor.py::driver_select_whys / rerank_whys`; `orchestrator/config.py::Budget`; `benchmarks/appworld/evolve/eval.py` |
| ③ Free pruning: beacon_guard + preflight | beacon: the editor rejects python edits without `activation_beacon` (hard); preflight: `make_zero_hit_preflight` zero-hit prune, **off by default** (see §6 ①) | `benchmarks/appworld/evolve/editor.py`; `orchestrator/production.py::make_zero_hit_preflight`; `benchmarks/appworld/evolve/run.py` (`zero_hit_preflight=False`) |
| ④ G5, apply, create child node | Candidate Manifest G5 binds label, `PatchWhere`, raw content digests, targets, fixture, evaluator, activation policy, and exact mutable surface before edit-then-commit. A rejection creates no child commit. The supported runtime label has an executable Focused-Fisher evidence binding; accepted train-side evidence creates a commit-bound manual activation and rollback bundle without touching the live tree. Sealed results remain outside promotion and are reviewed only after finalization | `evolver/candidate_manifest.py`; `evolver/candidate_evidence.py`; `evolver/applier/path_guard.py`; `orchestrator/production.py::make_git_commit_apply_fn`; `evolver/activation/artifacts.py` |
| ⑤a K=1 anchor generous-pass screen; σ_screen computed; cull at 1.5σ; three tiers | three buckets clear_win / within_band / cull, only cull is blocked; σ formula identical to the SOP, emitted by `select_anchor` from the ledger; the AppWorld line uses a focused-subset Fisher probe variant (also generous-pass: culls only significantly-worse) | `orchestrator/nodes/screen.py::screen_candidate`; `evolver/scheduler/anchor_selection.py::select_anchor / simple_anchor`; `orchestrator/gates/strategies.py::FocusedFisherGate` |
| ⑤a anchor composition: affinity majority + icebreakers + sentinels, ⊂ train | all three roles implemented; the sentinel guard adds stratification the SOP does not have (stable = mean guard, fragile = Fisher, avoiding noise kills); the affinity data source is unwired (§6 ③) | `evolver/scheduler/anchor_selection.py`; `orchestrator/gates/strategies.py` (sentinel guard) |
| ⑤ Borrowing (SOP tags [defer]) | module present (byte-identical to upstream), unwired (§6 ②) | `evolver/scheduler/tree_aware_bandit.py` |
| ⑤b Survivors: full set x K=3 confirm | `k_confirm=3`, confirm runs the full train set | `orchestrator/gates/strategies.py` |
| ⑥ Three shields in order Gate-f -> Gate-b -> Gate2 | `run_gates` is exactly this order; Gate-f first classifies measured, failed, or inconclusive evidence and fails closed. Gate-b fails OPEN without instrumentation data; the reported score always uses the full-set fixed denominator | `orchestrator/scoring.py::measurement_validity`; `orchestrator/gates/pipeline.py::run_gates`; `orchestrator/production.py` (beacon-aware `fired_source`) |
| Gate-b data chain | write side: the editor forces inline beacons -> per-attempt beacon directories; read side: union over the confirm dir + infra-ladder siblings. Honesty note: attribution is presence-level — Gate-b proves *a* beacon in the candidate's code executed on a task, not that the beacon sat inside the mechanism's trigger condition; an unconditionally-placed beacon degrades Gate-b to a no-op (promotion still requires the full-train win) | `evolver/activation/ledger.py::beacon_workspace / mark_beacons_enabled` (called from `benchmarks/appworld/batch.py`); `evolver/activation/ledger.py::read_fired_tasks` |
| ⑦ Best of bank becomes parent; all dead -> keep the old parent + fresh diagnosis | `beat_vanilla` patience signal + greedy parent selection | `orchestrator/loop.py` |
| Termination: 10 measured rounds with nobody above vanilla (vs vanilla, not the previous parent) or 20-round cap; never consult test | `TerminationTracker(patience=10, max_rounds=20)`, the signal defined as beating the FIXED vanilla. Failed-only and inconclusive-only rounds do not burn patience; they use `max_consecutive_errors` as a bounded no-decision backstop | `orchestrator/termination.py` |
| Candidate lifecycle statuses and evidence verdicts | node status includes `rejected_at_manifest / pruned_inert / pruned_at_screen / pruned_at_confirm / promoted_to_baseline / errored / blocked_l1 / archived-methodology-failure`; the independent durable verdict is exactly `accepted / rejected / failed / inconclusive` | `evolver/tree/node.py::NodeStatus`; `orchestrator/scoring.py::EvaluationVerdict`; `orchestrator/state/journal.py::RoundJournal` |
| WHERE bound mechanically from the artifact, never by self-declaration | `bind_where` derives the lever from the actually-touched files; the self-declared `patch_where` stays in the ledger for audit and never decides the archive coordinate (4-tier granularity, see §6 ④) | `orchestrator/archive.py::bind_where / cell_of` |

## 4. SOP §3 persistence -> implementation

| SOP layer | Pico counterpart |
|---|---|
| findings work log | `<work_dir>/findings.md` (one section per round, driver verdict) |
| Cross-session state | journal (`orchestrator/state/journal.py`, crash-resume replays completed rounds) + `history.json` (per-WHY attempt history) |
| Box durable artifacts | `failure_map.json` / `nodes/<id>.json` / per-round out-dirs / `activation/<id>/` Candidate Manifest, evidence, before, after, and rollback snapshots / byte-stable `evolution_summary.json` |

The git + node-ledger dual source of truth (SOP §3.1) carries over
isomorphically: code state lives in git commits (`commit_files_as_child`
produces real SHAs), tree lineage in `nodes/*.json`, aligned via
`git_commit_sha`.

## 5. Where we exceed the SOP

- **The sealed-test runner is mechanized.** SOP §8.2/§9.2 books its own
  sharpest debt: "not building yet; interim relies on discipline; reviewers
  will challenge it". Pico's `SealedTestRunner` + `assert_no_test_leak` is
  exactly the mechanism isolation the SOP demands — the upstream's sharpest
  methodological debt does not exist here.
- **A single candidate's crash cannot sink a round:** the `errored` status +
  errored rounds not burning patience (`max_consecutive_errors` as its own
  backstop); not covered by the SOP.
- **QD archive and recombination:** a (WHERE x WHY) per-cell elite bank +
  cross-cell recombinant candidates (`orchestrator/archive.py`) — an
  exploration mechanism beyond the SOP; gates and calibers unchanged.
- **The inert-death feedback loop** (2026-07): a distinct `pruned_inert`
  status + inert deaths recorded into history + the design prompt
  distinguishing "the trigger never fired" from "the mechanism was rejected"
  + gentle WHY decay for inert deaths (`0.55^n_fail x 0.85^n_inert`).
- **Harm replay:** when a candidate breaks a task, the regressed task's actual
  trajectory excerpt under that candidate is fed to the next design attempt;
  the SOP only requires flip counts.

## 6. Deliberate deviations and unwired parts (honest list)

1. **zero-hit preflight is off by default** (`zero_hit_preflight=False`,
   decided 2026-07). Rationale: Gate-b already denies credit to never-fired
   mechanisms (no correctness hole); preflight only saves budget, at a small
   false-prune risk; TRIGGER_REGEX declaration is opt-in and the actual prune
   rate is unknown. Gather data first (enable on a run, inspect
   `pruned_inert` entries in history), then decide the default. SOP §2 tags ③
   as [now]; this is a deliberate deviation.
2. **Borrowing unwired** (SOP §2 ⑤, tagged [defer]): `tree_aware_bandit` is
   present, the orchestrator does not call it. The AppWorld train set is
   affordable to run in full — consistent with the SOP's "small benchmarks
   don't need it"; wire it for large task sets.
3. **Affinity anchor lacks a data source:** `select_anchor(affinity)` accepts
   it; the appworld side has no trigger-density source (upstream's
   `affinity_picker.py` was not ported). Anchors are currently icebreakers +
   sentinels + borderline; screening still works, information efficiency is
   slightly lower.
4. **WHERE mechanical binding has 4 tiers** (prompt/runtime/mixed/edit),
   coarser than the judge schema's 14 classes. Sufficient for QD cells;
   refine `_lever_of_path` for fine-grained lever statistics. Self-declared
   and mechanical values are both in the ledger; no reconciliation alarm
   (an optional observability add-on).
5. **`pruned_inert` matches the SOP's status semantically** but differs in
   implementation: the SOP judges it via a preflight CLI, we via the embedded
   loop preflight (default off, see ①).

## 6.5 The unified entry (added 2026-07)

SOP §8.3's "manual orchestration" is superseded by
`pico evolve run --config <yaml>`: a single-command state machine
running cold start -> rounds -> termination -> unseal, resumable after any
interruption (artifacts are the state: trial files / journal / meta stamps,
three tiers of truth). Config drift and unseal one-wayness are mechanized in
`run_meta.json` (the codification of SOP §0's same-regime discipline).
Benches plug in via the contract in
[`evolve-bench-contract.md`](evolve-bench-contract.md); implementation in
`pico/evolver/launch/` + `pico/evolver/cli.py`.

## 7. SOP parts <-> Pico parts quick reference

| Part cited in SOP §8.1 | Pico counterpart | Shape difference |
|---|---|---|
| `analysis/proxy_features.py` | `evolver/analysis/proxy_features.py` | byte-identical |
| `analysis/failure_map_builder.py` | `evolver/analysis/failure_map_builder.py` | byte-identical |
| `activation/preflight.py` (CLI) | `orchestrator/production.py::make_zero_hit_preflight` | CLI -> embedded; regex variant, default off |
| `analysis/stability_bucket.py` | `evolver/analysis/stability_bucket.py` | byte-identical |
| `scheduler/bandit_tasks.py` | `evolver/scheduler/bandit_tasks.py` | byte-identical |
| `scheduler/anchor_selection.py` | `evolver/scheduler/anchor_selection.py` | same lineage + our `simple_anchor` |
| `scheduler/affinity_picker.py` | **no counterpart** (§6 ③) | — |
| `scheduler/tree_aware_bandit.py` | `evolver/scheduler/tree_aware_bandit.py` | same lineage, unwired (§6 ②) |
| `activation/gate_audit.py` (CLI) | `orchestrator/gates/pipeline.py::run_gates` (Gate-b embedded) | CLI -> embedded |
| `analysis/paired_significance.py` (CLI) | `orchestrator/gates/paired.py::paired_lift`; retention in `sealed/runner.py::unseal_retention` | CLI -> embedded |
| `aggregate_keq3` / `gate0_ctrf_audit` (external eval engine) | `benchmarks/appworld/evolve/eval.py / adapter.py` (K=3 aggregation + infra ladder) | cross-repo contract -> same-repo module |
| `tree/*` | `evolver/tree/` (node/store/git_ops) | same lineage + our `commit_files_as_child` / `read_file_at` |
