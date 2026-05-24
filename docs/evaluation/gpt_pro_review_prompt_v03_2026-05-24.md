# GPT Pro Review Prompt: PicoBench v0.3 Candidate

Update note: this prompt captured the `2c7b9df` review handoff. Post-review
fixes reclassified unsupported dogfood labels to `pico-inspired-synthetic`,
downgraded the resume proxy to checkpoint artifact smoke, and quarantined the
subagent proxy. For current status, read
`docs/evaluation/picobench_v03_results_summary.md` first.

请你以 benchmark / coding-agent harness reviewer 的角度 review 这个分支：

- repo: `Hackerismydream/pico`
- branch: `codex/picobench-v3`
- commit under review: pending final commit after this document
- scope: PicoBench v0.3 candidate, moving from v0.2 internal candidate toward
  "mini SWE for Pico"

## User Intent

目标不是把 synthetic task 堆到 100，也不是为了提高 pass rate 改 hidden
tests。目标是把 PicoBench 从 v0.2 internal candidate 推向更像 "mini SWE for
Pico" 的 v0.3：

- 修掉 `agentic_native_memory_001` 的 evidence bundle blocker，或正式
  quarantine。
- 给 Phase 3C core30 的 8 个失败做正式 triage。
- 对 8 个失败做两轮 targeted stability rerun。
- 区分 native PicoBench evidence 和 delegated human-gate evidence。
- 复核 latest HEAD no-key CI。
- 扩到 60 个 live/agent tasks：core 40、agentic-native 8、human-gate 12。
- 新增 dogfood authoring 流程和 scaffold。
- 给出 ready / not ready for v0.3 live run 的明确结论。

## Codex Output Summary

### Code / Benchmark Changes

- `benchmarks/picobench-core-v1.yaml`
  - core tasks expanded from 30 to 40.
  - added `core_031`-`core_040`.
  - 10 new visible fixtures and 10 new hidden fixture directories were added.
  - at least 8 of 10 are multi-file tasks.
  - original review found 6 unsupported `pico-dogfood-derived` labels; they
    were later reclassified as `pico-inspired-synthetic`.
- `benchmarks/picobench-agentic-native-v0.yaml`
  - fixed `agentic_native_memory_001` by replacing slash-only prompt with a
    remember-plus-confirmation turn and increasing step budget.
- `benchmarks/picobench-agentic-native-v1.yaml`
  - new v1 suite with 8 native tasks.
- `pico/evaluation/cli_runner.py`
  - emits `evidence_mode=native` for native runs.
  - emits `evidence_mode=delegated_human_gate` for v3 human-gate delegated runs.
- `pico/evaluation/report_card.py`
  - delegated human-gate evidence consistency now reports `not_applicable`.
  - mixed suites compute evidence consistency only over native evidence tasks.
- `pico/evaluation/task_quality.py`
  - supports per-task executable quality expectations:
    `quality.initial_public` and `quality.initial_hidden` as `pass|fail|either`.
- `scripts/build_picobench_dogfood_task.py`
  - scaffolds visible fixture dir, hidden fixture dir, and benchmark task stub.

### Docs Added / Updated

- `docs/evaluation/phase3c_core30_failure_triage.md`
- `docs/evaluation/phase3c_failure_stability.md`
- `docs/evaluation/dogfood_task_authoring.md`
- `docs/evaluation/picobench_v03_expansion_plan.md`
- `docs/evaluation/picobench_v03_results_summary.md`
- `docs/evaluation/agentic_native_v1_plan.md`
- `docs/evaluation/agentic_native_evidence_review.md`
- `docs/evaluation/live_results_summary.md`
- `docs/evaluation/live_execution_log.md`
- `docs/evaluation/phase3_plan.md`

## Verification Results

### No-Key Gates

Command:

```bash
uv run pytest tests/ -q
uv run python scripts/check_picobench_tasks.py \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --min-tasks 40 \
  --json-output /tmp/picobench-latest-quality.json
uv run python scripts/run_picobench_runtime.py \
  --benchmark benchmarks/picobench-runtime-v1.json \
  --output-dir /tmp/picobench-latest-runtime \
  --json
```

Result:

- pytest: `271 passed, 2 skipped, 6 warnings`
- task quality: 40 tasks, 40 hidden fixtures, no issues
- runtime: 2/2 passed

### New Core Executable Quality

Command:

```bash
uv run python scripts/check_picobench_tasks.py \
  --benchmark benchmarks/picobench-core-v1.yaml \
  --task core_031 --task core_032 --task core_033 --task core_034 --task core_035 \
  --task core_036 --task core_037 --task core_038 --task core_039 --task core_040 \
  --min-tasks 10 \
  --run-public-tests \
  --run-hidden-tests \
  --require-initial-failing \
  --json-output /tmp/picobench-quality-new10.json
```

Result: passed, 10 tasks, 10 hidden fixtures, no issues.

### Agentic-Native Memory Evidence Fix

Run: `/tmp/picobench-agentic-native-rerun2`

- tasks: 3
- strict pass: 3/3
- evidence consistency: 1.0

### Phase 3C Targeted Stability

Runs:

- `/tmp/picobench-phase3c-failures-rerun-1`: 2/8 strict pass, evidence consistency 1.0
- `/tmp/picobench-phase3c-failures-rerun-2`: 1/8 strict pass, evidence consistency 1.0

Stable hidden failures:

- `core_016`
- `core_018`
- `core_019`
- `core_023`
- `core_027`
- `core_028`

Stability-sensitive:

- `core_029`: original full-run process failure, passed both targeted reruns.
- `core_030`: original full-run hidden failure, passed attempt 1, failed attempt 2.

### New Core Live Smoke

Runs:

- `/tmp/picobench-v03-new-core-a`: 4/5 strict pass, evidence consistency 1.0
- `/tmp/picobench-v03-new-core-b`: 5/5 strict pass, evidence consistency 1.0

Only strict failure: `core_032` hidden manifest edge.

### Agentic-Native v1 Live Smoke

Run: `/tmp/picobench-v03-agentic-native`

- tasks: 8
- strict pass: 6/8
- evidence consistency: 1.0
- failures:
  - `agentic_native_resume_001`: `public_test_failure`
  - `agentic_native_subagent_001`: `step_budget_exceeded`

## Review Questions

1. Is the v0.3 task expansion credible as a step toward "mini SWE for Pico", or
   are the new core tasks still too synthetic?
2. Are `core_031`-`core_040` valid benchmark tasks, especially the
   dogfood-derived labels and hidden edge expectations?
3. Is the delegated human-gate evidence treatment correct:
   `evidence_mode=delegated_human_gate` and `evidence_consistency=not_applicable`?
4. For `agentic_native_resume_001`, should the task be revised as a simple
   artifact smoke, or should it wait until the runner supports a true two-pass
   resume flow?
5. For `agentic_native_subagent_001`, is the current proxy task useful, or
   should it be quarantined until there is a real subagent trace/session event?
6. Is the per-task executable quality metadata (`initial_public`,
   `initial_hidden`) appropriate, or does it create too much room for task
   authoring mistakes?
7. Based on the recorded evidence, is the correct recommendation "ready for
   v0.3 review run but not release-grade v0.3"?

## Expected Review Output

Please return:

- blocking issues
- non-blocking issues
- task validity concerns
- evidence/reporting concerns
- whether the branch should be accepted as v0.3 review candidate
- concrete fixes before final v0.3 release
