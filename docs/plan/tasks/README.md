# Pico delivery task index

This index separates the completed PicoBench package from the completed
Pico-side CodeCairn implementation and joint evidence package. A task with
`authority-issue: null` is not authorized to start.

## PicoBench Ship-1

> **Status: Completed.** GitHub Issue
> [#59](https://github.com/Hackerismydream/pico-harness/issues/59) owns
> PicoBench Ship-1, its CNY 100 Provider budget, and the permitted `pico/`
> Context-engine seam. All eight delivery slices and the formal campaign
> completed. The final task campaign is ship-complete but
> measurement-invalid; that fail-closed verdict is retained rather than
> converted into a positive capability result.

### Dependency graph

```text
picobench-001
  |               \
  v                v
picobench-002    picobench-007
  |
  +--------------+--------------+--------------+
  v              v              v              v
picobench-003  picobench-004  picobench-005  picobench-006
  \              |              |              /
   +--------------+--------------+-------------+
                         |
                         v
                  picobench-008
```

### Tasks

| Task | Status | Outcome |
| --- | --- | --- |
| [picobench-001](picobench-001.md) | completed | Canonical contract, plan identity, and artifact records |
| [picobench-002](picobench-002.md) | completed | Isolated full-runtime Trial Host and minimal experiment seams |
| [picobench-003](picobench-003.md) | completed | R0 Scheduler and R1 full-runtime deterministic tracks |
| [picobench-004](picobench-004.md) | completed | Long-context FIFO versus Curator Task Pack |
| [picobench-005](picobench-005.md) | completed | Memory/Skill retrieval and cross-session Task Pack |
| [picobench-006](picobench-006.md) | completed | Real local MCP Tool-disclosure Task Pack |
| [picobench-007](picobench-007.md) | completed | Pair reducer, statistics, Claim Gates, and report rebuild |
| [picobench-008](picobench-008.md) | completed | Calibration, frozen campaign, and Ship verdict |

The tracked task cards and implementation are reviewable repository artifacts.
Raw Trials, traces, live Memory content, and generated reports stay under
`.pico/evidence/picobench/` and are not committed.

### Common completion Gates

The command in each task card is its focused minimum. Every implementation
slice also runs:

```bash
uv run --extra dev ruff check benchmarks/picobench
uv run --extra dev ruff format --check benchmarks/picobench
make check-large-files
```

Each task also Ruff-checks and format-checks the exact Python test files listed
in its owned paths.

When a task modifies the authorized product-side Context seam, it additionally
runs:

```bash
uv run pytest \
  tests/test_cli_runtime_assembly.py \
  tests/test_default_context_engine.py \
  tests/test_runtime_host_contracts.py \
  -q
```

Before a prepared task starts, its accepted GitHub authority is copied into
`authority-issue` and its status changes from `blocked` to `ready`. Development
sets it to `in-progress`; the merge that satisfies its acceptance Gates sets it
to `completed`. A task with `authority-issue: null` is not ready even when all
dependencies are present.

## CodeCairn Memory replacement

> **Status: Pico-side implementation and joint verification complete.**
> GitHub Issue
> [#65](https://github.com/Hackerismydream/pico-harness/issues/65) authorized
> `codecairn-001` and `codecairn-002` at CNY 0. Issue
> [#70](https://github.com/Hackerismydream/pico-harness/issues/70) completed
> `codecairn-003` under the cumulative CNY 100 ceiling.

### Dependency graph

```text
CodeCairn v02-001 + v02-002
              |
              v
        codecairn-001
              |
              v
        codecairn-002
              |
              v
        codecairn-003
              |
              v
 CodeCairn v02-003 evidence state-sync
```

### Tasks

| Task | Status | Outcome |
| --- | --- | --- |
| [codecairn-001](codecairn-001.md) | completed | consume installed Adapter, switch default, and close startup behavior |
| [codecairn-002](codecairn-002.md) | completed | remove EverOS product coupling and preserve Local Skills |
| [codecairn-003](codecairn-003.md) | completed | installed M2/M4 passed; M5 completed 32/32 Trials and 16/16 valid Pairs, with positive claim ineligible on hard-negative injection |

The completed execution Goal for `codecairn-003` is
[`pico-codecairn-joint-evidence-goal.md`](../pico-codecairn-joint-evidence-goal.md).
Issue #70 contains the immutable Stage A pair, paid authorization, retained
failed attempts, final valid measurement, Claim Gate result, budget ledger,
and completion handoff.

The cross-repository Interface is fixed in the
[CodeCairn backend contract](../../specs/codecairn-memory-backend.md). The
[delivery analysis](../analysis/codecairn-memory-replacement.md) owns the
deletion map, integration enumeration, rollout order, and completion boundary.

### Common completion Gates

Every implementation slice must:

- keep Pico dependent only on the public `MemoryBackend` Interface;
- use an installed CodeCairn Plugin for integration claims;
- keep `memory.backend = null` as a zero-CodeCairn-backend-operation baseline;
- preserve Local Skills;
- fail closed rather than return empty Memory on setup, import, index, or
  persistence failure;
- keep historical EverOS artifacts unchanged;
- run focused tests, retained affected tests, V-P0 when selected by the task
  card, and `make check-large-files`. Historical V-O0 is not a current Gate;
  CodeCairn continuity requires a separately authorized replacement.

Any future campaign after a CodeCairn abstention repair requires a new
issue-approved Provider/model, immutable inputs, and cost ceiling. Neither the
completed Issue #70 authorization nor the earlier PicoBench authorization
funds a new campaign.
