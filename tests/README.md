# Pico test suite

This page maps test layers to product claims. Exact commands and release
verifiers are also documented in [`docs/dev.md`](../docs/dev.md).

## Test layout

| Path | Meaning |
| --- | --- |
| `tests/test_*.py` | deterministic unit and cross-module tests |
| `tests/integration/test_*.py` | process, Provider, Channel, VM, or end-to-end integration |
| `tests/tui/autotest/` | black-box terminal-process harness |
| `tests/tui/` and `ui-tui/` tests | TUI client, RPC, and rendering contracts |
| `tests/integration/data/` | synthetic executable fixtures |

Follow `AGENTS.md` naming rules. CLI tests use
`test_cli_<module>_commands.py`; integration names describe a feature/resource,
not an issue or phase number.

## Fast development checks

Default focused Python CI:

```bash
make lint-python
make test-python
```

Full TUI checks:

```bash
make lint-tui
make test-tui
make build-tui
```

Tests should avoid live network calls by default. When a test needs external
services or a real model, guard it behind an explicit marker or environment
variable so CI and local contributors get deterministic results.

The deterministic Channel contract and security bundles (V-C0 and V-S0) run by
`make verify-channels` from `scripts/verify_channels.py`. The live Feishu
tracer bullet (V-LF) lives in `tests/integration/test_feishu_real_channel.py`
behind the `real_channel` marker and is orchestrated by
`scripts/verify_live_feishu.py`; see
`docs/specs/channel-evidence-gates.md` for both Gates.

`make ci` combines focused lint/tests and the TUI build. It is a development
Gate, not complete release acceptance.

## Retained deterministic suite

Run all deterministic Python tests, with every retained optional extra
installed and dependency versions frozen:

```bash
make test-retained
```

This excludes tests marked:

- `real_llm`;
- `llm_judge`;
- `real_vm`;
- `real_channel`;
- `external_runtime`;
- `e2e`.

The exclusions are evidence boundaries, not waivers. A required issue or
release Gate must run its corresponding live layer explicitly.

For focused work:

```bash
uv run pytest tests/test_cli_doctor_commands.py -x
uv run pytest tests/test_context_invariants.py -q
```

Always run pytest through `uv`.

## Integration markers

| Marker | External requirement | Claim boundary |
| --- | --- | --- |
| `real_llm` | live model or embedding endpoint | may incur cost and fail on Provider infrastructure |
| `llm_judge` | model used as grader | adds cost and non-determinism |
| `real_vm` | BoxLite/VM runtime | requires supported virtualization |
| `real_channel` | external messaging platform | real platform evidence |
| `external_runtime` | wheel, executable, or service outside test environment | installed/runtime boundary |
| `e2e` | real subprocess through TUI autotest | black-box terminal boundary |

Optional diagnostic run:

```bash
uv run pytest -m real_vm -q -rs
```

A skip is useful diagnostics when a resource is optional. If the Gate declares
that resource required, a skip, infrastructure failure, or inconclusive result
must fail the Gate.

## Named verification Gates

| Gate | Command | Proves |
| --- | --- | --- |
| V-D0 | `make test-retained` | current deterministic retained behavior |
| V-T0 | TUI lint, RPC checks, type check, tests, build | current TUI contract |
| V-P0 | `scripts/verify_distribution.py` | isolated build, exact wheel boundary, extras, installed probes, sdist equivalence |
| deterministic host Gate | `make verify-runtime-hosts` with `PICO_WHEEL` | installed CLI/TUI/Gateway parity against deterministic endpoint |
| V-LP | `make verify-live-provider` | one required real Provider through installed hosts |
| V-C0 / V-S0 | `make verify-channels` | deterministic Channel contracts, SDK laziness, deny-by-default policy, and adapter isolation |
| V-LF | `make verify-live-feishu` | operator-in-the-loop real Feishu tracer bullet; passed against the real Pico bot on 2026-07-27 |
| V-TE0 | `make verify-turn-evidence` | deterministic Turn trace, usage, delivery, and terminal-state correlation |
| V-E0 | `make verify-evolver` | deterministic Evolver lifecycle, Gates, evidence, activation artifacts, rollback |
| V-R0 | `make verify-release` | one clean release commit satisfying every required layer; currently fail-closed on the blocked CodeCairn continuity layer |

`--help`, a successful import, a mock, a fixture, or a model-list endpoint is
not a substitute for these behavior-level Gates.

## Evidence result vocabulary

Report at least:

- deterministic or fixture-backed pass;
- live pass and named resource;
- failed assertion;
- Provider failure;
- infrastructure failure;
- inconclusive;
- skipped.

Do not convert removed behavior to `skip` or `xfail` merely to keep the suite
green. Remove its tests or retarget them to the retained contract.

## Test isolation

- use temporary Pico roots and initialized temporary Git repositories for
  CodeCairn integration tests;
- never write real keys into fixtures, command output, or reports;
- bind evidence to the tested commit;
- use synthetic ids and content for live services;
- keep report assets and large logs outside Git;
- restore environment and process state after each test;
- do not rely on a source checkout when testing an installed wheel.

## TUI autotest

The black-box harness requires the external `tui-use` CLI and is documented in
[`tests/tui/autotest/README.md`](tui/autotest/README.md). Its `e2e` tests are
outside the default deterministic suite.
