# Pico Developer Guide

Start with the [documentation index](INDEX.md), [architecture map](architecture/README.md),
and [project status](project-status.md). This guide owns executable setup and
verification commands; it does not define product scope or make an older Gate
result apply to the current commit.

## Build and run from source

Pico uses Python 3.12, Node.js 22, `uv`, and Hatchling. Node.js is required for
the native TUI build and runtime.

### 1. Install dependencies

```bash
cd /path/to/pico-harness
uv sync
```

Optional extras:

```bash
uv sync --extra channels
uv sync --extra sandbox
uv sync --extra tools
uv sync --all-extras
```

The `channels` extra contains only Feishu, QQ, and WeCom.

### 2. Run the CLI

```bash
uv run pico --help
uv run pico onboard
uv run pico
```

Onboarding writes Pico-owned configuration under `~/.pico`. Foreground commands
operate on the current directory and keep Workspace State under
`~/.pico/projects/<project-id>`; Gateway keeps the configured
`~/.pico/workspace` default.

To use a non-default location, pass an explicit `--config` or `--workspace`
path. This is an opt-in path override with colocated state, not an implicit
state import.

### 3. Common commands

| Command | Description |
| --- | --- |
| `pico run` | Start an interactive terminal Session |
| `pico run -m "Hello"` | Execute one Turn and exit |
| `pico gateway` | Start Channels, Cron, and health services |
| `pico status` | Show configuration, Workspace, and Provider status |
| `pico channels status` | Show Feishu, QQ, and WeCom readiness |
| `pico provider login <name>` | Authenticate with an OAuth Provider |
| `pico sessions list` | List resumable Sessions |
| `pico tracing` | Open the local Tracing dashboard |

### 4. Verification

Use the repository commands so local checks match CI:

```bash
make lint-python
make lint-tui
make test-retained
make test-tui
make check-large-files
```

Run focused Python tests with `uv`:

```bash
uv run pytest tests/test_cli_smoke.py -x
```

`make ci` is the smaller development check used by default CI. It does not run
V-D0 or the release and live Gates below.

### Gate catalog

| Gate | Command or owner | Evidence boundary |
| --- | --- | --- |
| V-D0 | `make test-retained` | deterministic retained Python behavior |
| V-T0 | `make lint-tui && make test-tui && make build-tui` | TUI lint, RPC schema and surface, types, tests, and bundle |
| V-P0 | `scripts/verify_distribution.py` | isolated wheel and sdist, exact package boundary, extras, and installed probes |
| deterministic host Gate | `make verify-runtime-hosts` with `PICO_WHEEL` | installed CLI, TUI, and Gateway against a deterministic Provider |
| V-LP | `make verify-live-provider` | one required real Provider through installed hosts |
| V-C0 and V-S0 | `make verify-channels` | deterministic Channel contract plus security and adapter-isolation selections |
| V-LF | `make verify-live-feishu` | required real Feishu tracer bullet; passed against the real Pico bot on 2026-07-27 |
| V-TE0 | `make verify-turn-evidence` | deterministic Turn trace, usage, delivery, and terminal-state correlation |
| V-E0 | `make verify-evolver` | deterministic Evolver lifecycle and evidence contracts |
| V-R0 | `make verify-release` | fail-closed aggregation on one clean release commit; driver implemented, no full pass recorded |

A `--help` probe, successful import, fixture, skipped live test, or reachable
model-list endpoint does not substitute for the behavior-level Gate named by
an issue.

### V-P0 distribution gate

V-P0 is the canonical release build and verification path. Run it with a fresh
output root outside the source checkout:

```bash
vp0_root="$(mktemp -d)/pico-distribution"
uv run python scripts/verify_distribution.py \
  --output-root "$vp0_root" \
  --entrypoint pico \
  --extras base,channel-feishu,channel-qq,channel-wecom,channels,sandbox
```

The verifier builds the TUI, wheel, and source distribution from an isolated
source snapshot. It enforces the exact wheel manifest, installs the base package
and each retained extra into separate environments, and probes the installed
CLI, TUI, Gateway, help, and doctor paths with an empty `PYTHONPATH` and no
source checkout.

The wheel is self-contained at the package boundary: it ships exactly one
compiled TUI bundle and does not require npm or repository sources after
installation. It intentionally does not embed a Node.js executable, so Node.js
22 remains a host runtime requirement for the TUI.

Pico retains the source distribution as a release artifact. V-P0 rebuilds a
wheel from that source distribution and requires it to match the directly built
wheel file-for-file and content-for-content, excluding only the generated wheel
`RECORD`.

On success, `$vp0_root/distribution-report.json` uses schema version 3. Its
stable downstream handoff is:

| Field | Meaning |
| --- | --- |
| `handoff.wheel` | Verified wheel path for V-LP, V-LF, and V-R0 |
| `handoff.base_environment.root` | Installed base environment root |
| `handoff.base_environment.python` | Python executable in the base environment |
| `handoff.base_environment.entrypoint` | Installed `pico` executable |

Downstream gates must consume these fields only when `status` is `passed`. The
paths belong to the current V-P0 output root and are not portable after that
directory is removed.

### Runtime Hosts and V-LP

Consume the verified wheel from V-P0 before testing an Agent Turn:

```bash
export PICO_WHEEL="$(
  python3 -c 'import json,sys; report=json.load(open(sys.argv[1])); assert report["status"] == "passed"; print(report["handoff"]["wheel"])' \
    "$vp0_root/distribution-report.json"
)"
make verify-runtime-hosts
```

`verify-runtime-hosts` creates a new environment, installs `PICO_WHEEL`, and
runs the same protected file-reading task through CLI, TUI, and Gateway against
a deterministic local OpenAI-compatible endpoint. It requires one successful
Tool call, non-empty usage, the expected stream mode, and imports from the
installed environment rather than the source checkout.

V-LP repeats that contract against one real Provider:

```bash
export PICO_LIVE_PROVIDER=deepseek
export PICO_LIVE_MODEL=deepseek/deepseek-chat
export PICO_LIVE_API_KEY=...
make verify-live-provider
```

Set `PICO_LIVE_BASE_URL` only for a custom or overridden endpoint. V-LP passes
the key to isolated child processes through the environment and never writes it
to its result. Missing credentials are reported as skipped during ad-hoc pytest
runs; `make verify-live-provider` enables required mode, where skipped,
inconclusive, failed, and infrastructure-failure results all fail the Gate.

### V-C0 and V-S0 Channel gates

Two deterministic Channel gates run from one driver:

```bash
make verify-channels
```

V-C0 is the Channel contract bundle: inbound dispatch and dedup, outbound
routing, allowlist enforcement, media handling, retryable versus terminal send
errors, malformed events, the CLI channel surface, and the registry. The
bundle inventory lives in `scripts/verify_channels.py`; new Channel-layer
deterministic tests join it in the same change.

V-S0 is the Channel security and isolation bundle. It is a named test selection
covering three claims: channel SDKs stay lazy so a base installation starts
without any channel extra, allowlists deny by default and each adapter rejects a
denied sender before any side effect, and one adapter failing (missing SDK,
crashing factory, or a deny-all allowlist) disables only that channel while the
other channels and the Gateway still start.

Evidence lands in `.pico/evidence/channels/channels-report.json` with schema
`pico.channels.evidence.v2`, carrying `gate: V-C0`, `security_gate: V-S0`, a
hashed log and the exact test selection per bundle. The command prints
`V-C0 <status>` and `V-S0 <status>`, and exits 0 only when both passed. Both
bundles are deterministic: a skip or an expected failure fails the gate, and no
result may be reported as live Channel evidence.

QQ and WeCom are Beta on this evidence alone. See
[channel-evidence-gates.md](specs/channel-evidence-gates.md) for the per-adapter
contract matrix, the manager isolation semantics, and what Beta does not claim.

### V-LF live Feishu gate

V-LF is the required real Feishu tracer bullet: a real inbound message and
reply, one attachment in, one `MediaOut` out, and a Cron job that survives a
Gateway restart and delivers exactly once - all through a disposable
`PICO_HOME` with an isolated config, never the operator's real state. A human
operator provides the inbound stimulus; the harness automates observation,
restart orchestration, classification, and redaction.

```bash
export PICO_LIVE_FEISHU_APP_ID=...
export PICO_LIVE_FEISHU_APP_SECRET=...
export PICO_LIVE_FEISHU_OPERATOR_ID=ou_...
export PICO_LIVE_API_KEY=...
make verify-live-feishu
```

Required mode turns missing credentials, skipped phases, and timeouts into
Gate failures. Set `PICO_WHEEL` to run the Gateway from a verified installed
wheel instead of the checkout; the report records `runtime_source` either
way. Evidence is written to `.pico/evidence/feishu/feishu-live-report.json`;
secrets never enter it and platform identifiers are digested. Feishu may be
described as production-verified only for the exact commit and scenario a
passed V-LF run captured. See
[channel-evidence-gates.md](specs/channel-evidence-gates.md).

### V-TE0 turn evidence gate

V-TE0 verifies that one Turn's tracing, usage, and delivery evidence actually
joins, and that its terminal states stay distinguishable:

```bash
make verify-turn-evidence
```

The Gate runs a deterministic scenario that drives six Spine Turns through
scripted runners and outlets -- success, Tool failure, Provider failure, runner
error, cancellation, and delivery exhaustion -- into a temporary trace root,
then validates the artifacts: each Turn chains `spine.turn` to `session.turn` to
its `llm.call` and `tool.call` spans on one trace id, usage rows join by
`trace_id` and `turn_span_id`, delivery spans and `DELIVERY_FAILED` notices join
by trace and conversation, and the five Turn terminal states are pairwise
distinct. Incomplete or contradictory event sets -- a Turn with no terminal
state, an outcome that disagrees with its span status, an orphaned
`session.turn`, a usage row pointing at a trace with no Turn -- are reported as
findings rather than passed over.

Evidence is written to
`.pico/evidence/turns/turn-evidence-report.json` (schema
`pico.turn.evidence.v1`), with the scenario log captured beside it and
referenced by `log_sha256`. The report stores ids, labels, and counts only --
never message content, Tool arguments, prompts, or Provider keys. Deterministic,
contract, live, infrastructure-failure, and inconclusive results are separate
states; only a passed scenario plus passed contract checks make V-TE0 pass, and
a skipped or inconclusive check never does. V-TE0 spends no live model calls and
must not be reported as a live or production result.

The contract it enforces is
[`specs/turn-evidence-correlation.md`](specs/turn-evidence-correlation.md).

### V-E0 Evolver gate

V-E0 is the deterministic acceptance gate for the opt-in Evolver Beta:

```bash
make verify-evolver
```

It covers the public `pico evolve check|run|status|finalize` surface, readiness
validation, four-way evidence verdicts, Candidate Manifest G5 checks, scorer
and path isolation, manual runtime activation, rollback artifacts, and a
fixture-backed cross-process Evolution Run. The fixture starts a run, resumes
the same journal from a new process, reads status twice from fresh processes,
and finalizes twice while proving `evolution_summary.json` remains byte-stable.
V-E0 spends no live model calls and must not be reported as a production
benchmark result.

### V-R0 release candidate gate

V-R0 is the last Gate. It runs every other Gate in one pass, binds all of them
to one commit, and writes a single report:

```bash
make verify-release
```

The driver is [`scripts/verify_release.py`](../scripts/verify_release.py);
`--output-root` is required and the Makefile target points it at
`.pico/evidence/release`. Evidence lands in
`.pico/evidence/release/release-report.json` (schema
`pico.release.evidence.v1`), with one hashed log per layer under
`.pico/evidence/release/logs/`. The command prints one progress line per layer
it runs and finishes with `V-R0 <status>: <path>`, exiting 0 only when the
status is `passed`.

Layers run in dependency order: `v_d0`, `v_t0`, `v_p0`, `host_gate`, `v_lp`,
`v_c0_s0`, `v_lf`, `memory_continuity`, `v_te0`, `v_e0`, `deps_audit`, `assets`,
`evolution`. V-P0 builds and verifies the wheel into a fresh temporary root,
and the host, live-provider, and Evolution Run layers consume that wheel from
the V-P0 handoff. That temporary root stays on disk after the run so its
installed environments remain inspectable; remove it yourself when finished.

Before starting, a full pass needs a clean checkout at the commit under test,
Node.js 22, `uv sync --all-extras`, and:

| Variable | Used by | Notes |
| --- | --- | --- |
| `PICO_LIVE_API_KEY` | `v_lp`, `v_lf` | Absent means both layers fail with a named credentials gap |
| `PICO_LIVE_PROVIDER`, `PICO_LIVE_MODEL` | `v_lp` | Select the live Provider and model |
| `PICO_LIVE_BASE_URL` | `v_lp` | Only for a custom or overridden endpoint |
| `PICO_LIVE_FEISHU_APP_ID` | `v_lf` | Real Feishu application credentials |
| `PICO_LIVE_FEISHU_APP_SECRET` | `v_lf` | Never written to the report |
| `PICO_LIVE_FEISHU_OPERATOR_ID` | `v_lf` | The human operator who sends the inbound stimulus |

`PICO_WHEEL` is not set by hand: the driver passes the V-P0 handoff wheel to
the layers that need it.

For development reruns, `--layers` takes a comma-separated subset:

```bash
uv run python scripts/verify_release.py \
  --output-root .pico/evidence/release \
  --layers v_te0,assets
```

A subset run writes the same report and records every unselected layer as a
named `layer_not_run` gap. Only the full set can report `passed`; there is no
flag that relaxes that.

Missing layers are always named gaps, never silent skips: absent live
credentials, an absent V-P0 handoff, absent small real Evolution Run inputs, a
sub-report recorded at another commit, a sub-report left behind by an earlier
run, and an uncommitted working tree all appear in `gaps` and keep the run from
passing.

Evidence from an earlier pull request, an earlier branch, or an earlier wheel
cannot substitute for a layer here, however green it was. V-R0's claim is that
the layers passed together at one commit; a report imported from another commit
is refused rather than merged.

## Repository identity

Public commands, help, templates, state paths, documentation, Python imports,
and source paths use Pico. Preserve [LICENSE](../LICENSE),
[NOTICES.md](../NOTICES.md), and [LICENSES/](../LICENSES/).
