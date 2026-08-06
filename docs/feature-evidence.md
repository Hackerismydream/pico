# Feature-to-evidence matrix

What each retained Pico capability is, where it is implemented, which Gate is
the strongest thing standing behind it, and what may honestly be claimed about
it today.

The rule this table exists to enforce: deterministic, contract, live,
provider-failure, and infrastructure results stay separate. A fixture is never
presented as live evidence, and a Provider or infrastructure failure is never
presented as a product result. Gate commands, required environment variables,
and evidence outputs are in [dev.md](dev.md). A study path through the same
layers is in [learning-path.md](learning-path.md).

## Evidence classes

| Class | Meaning |
| --- | --- |
| deterministic | An offline, rerunnable test bundle exercises the code. No model call, no network, no chat platform. |
| contract | A produced artifact or interface is validated against a written spec: the V-TE0 checks against `specs/turn-evidence-correlation.md`, the V-C0 per-adapter matrix in `specs/channel-evidence-gates.md`, and the V-P0 wheel manifest. |
| live | A real Provider or a real chat platform executed the path, for the exact commit and scenario a passed run recorded. |
| historical | A recorded past run whose external artifact carries a digest and source commit, not rerunnable at will. |

`skipped`, `inconclusive`, `provider_failure`, and `infrastructure_failure` are
result states, not evidence classes. None of them satisfies a required Gate.

## Matrix

| Capability | Implementation entry point | Strongest evidence gate | Evidence class | Current claim |
| --- | --- | --- | --- | --- |
| Deterministic Runtime benchmark | `benchmarks/picobench/packs/runtime/`, `benchmarks/picobench/campaign.py` | immutable Runtime evidence `1c9fc1c4882ff09e3cf44140d84206bfb5ce923344cf7e482615a36e4f0f6006` at clean source commit `e6c790e` | deterministic | R0 recorded 2,000 accepted Scheduler requests with zero lost requests, zero unexpected duplicate executions, and zero unresolved handles; P95 dispatch overhead was 0.761958 ms and P95 queue wait was 190.124417 ms. R1 submitted 100 deterministic requests through the Scheduler across success, Tool-failure, Provider-failure, and cancellation scenarios; 92 produced readable Session and Delivery outcomes. These are deterministic local observations, not live throughput or production SLOs. |
| Hosts (CLI, TUI, Gateway) | `pico/cli/_runtime_assembly.py`, `pico/cli/commands.py`, `pico/cli/gateway_commands.py`, `pico/tui_rpc/server.py` | `make verify-runtime-hosts`, consuming a V-P0 wheel | deterministic | One shared Runtime Assembly runs the same protected file-reading task through CLI, TUI, and Gateway from an installed wheel against a deterministic local endpoint, importing from the installed environment rather than the checkout. Real-Provider coverage for the same contract is V-LP and is operator-run. |
| Spine | `pico/spine/scheduler.py`, `pico/spine/turn.py`, `pico/spine/runner.py` | V-D0 Spine subset (`make test-retained`); V-TE0 for terminal states | deterministic | One entry and one exit, per-conversation Lanes as the ordering and cancellation unit, and independent origin pools are verified offline. V-TE0 additionally proves the five Turn terminal states are pairwise distinct. |
| Session | `pico/session/manager.py`, `pico/session/export.py` | V-D0 retained Session tests | deterministic | Session lifecycle and Portable Session Export remain usable from fresh processes. The export stays verifiable after the source Session is deleted. |
| Context | `pico/context_engine/assembler.py`, `pico/context_engine/curator.py` | V-D0 retained Context tests | deterministic | Curator budgeting and deterministic Fail-Safe selection are verified offline, including that the Fail-Safe takes over when no valid plan exists. No claim is made about the quality of a Slow Path plan produced by a live model. |
| CodeCairn Memory | `pico/memory_engine/backend.py`, installed `codecairn.integrations.pico` Plugin | Issue #70 installed M2/M4 Gate and formal experiment `1c5496edfaa08212635f6218f9aaa55c3e942fcd1e79203a11a6b8c4d9b94623` | deterministic, contract, live | The exact Pico `5318daa` and CodeCairn `a501fe2` pair passed installed continuity and completed 32/32 formal Trials with 16/16 valid Pairs. Treatment passed 16/16 Verifiers versus 0/16 for Memory-off; Recall@5 was 1.0 with zero stale injection, zero cross-repository leakage, and zero Memory-off operations. The measurement is valid but no positive metric is eligible because irrelevant injection was 3.0 against the frozen 0.05 maximum. |
| Historical EverOS Memory | removed Runtime; retained dated reports | PR #47 V-O0 | historical | The recorded real cross-process store/recall result applies only to the historical source commit and is not CodeCairn evidence. |
| Skills | `pico/memory_engine/skill_forge/router.py`, `pico/memory_engine/skill_local/local_pool.py` | V-D0 SkillForge subset and Issue #65 parity checks | deterministic | Local Skill BM25 retrieval, gating, and prompt injection are verified with CodeCairn selected and with Memory off. There is no remembered-Memory or remote marketplace source in the active path. |
| Plugins | `pico/plugin/registry.py`, `pico/plugin/manifest.py`, `pico/plugin/discover.py` | V-D0 Plugin subset and installed CodeCairn discovery | deterministic, contract | Generic manifest discovery, activation, `module:callable` factory resolution, and fail-closed conflict rejection remain verified. CodeCairn is an installed entry-point Plugin; Pico bundles no default Memory Plugin. |
| Providers | `pico/providers/registry.py`, `pico/providers/litellm_provider.py`, `pico/routing/router.py` | V-LP (`make verify-live-provider`) | live, operator-run | Adapter selection, fallback chains, and routing are deterministic-covered. A real Provider Turn may be claimed only for the exact Provider and model a passed V-LP run recorded. Missing credentials report as skipped in ad-hoc runs; required mode turns skipped, inconclusive, failed, and infrastructure-failure results into Gate failures. |
| Tools | `pico/agent/tools/registry.py`, `pico/agent/tools/base.py` | V-D0 Tool subset; V-TE0 for `tool.call` spans | deterministic | Name-to-Tool dispatch under a timeout and the explicit failure bit on `ToolResult` are verified offline. A Tool failure is recorded as `completed_with_tool_failure`, a completion with its own terminal value, not a Turn failure. |
| Channel: Feishu | `pico/channels/adapters/feishu/channel.py`, `pico/channels/adapters/feishu/spec.py` | V-C0 and V-S0 (`make verify-channels`); V-LF (`make verify-live-feishu`) | deterministic, contract, live | Live-gated. `ChannelSpec.maturity` is `live-gated`. A required V-LF run against the real Pico Feishu bot passed on 2026-07-27 with real inbound and outbound text, attachment input, `MediaOut`, WebSocket restart, and exactly-once Cron delivery. The report binds this claim to its recorded commit and scenario; V-C0 remains the evidence for duplicate suppression, error receipts, and the allowlist negative path. |
| Channel: QQ | `pico/channels/adapters/qq/channel.py`, `pico/channels/adapters/qq/spec.py` | V-C0 and V-S0 | deterministic, contract | Beta by deterministic contract only. `ChannelSpec.maturity` is `beta`. Inbound dispatch and dedup, outbound routing, allowlist enforcement, media handling, and retryable-versus-terminal send errors are covered offline. No live send or receive evidence exists, and none is claimed. |
| Channel: WeCom | `pico/channels/adapters/wecom/channel.py`, `pico/channels/adapters/wecom/spec.py` | V-C0 and V-S0 | deterministic, contract | Beta by deterministic contract only. `ChannelSpec.maturity` is `beta`. Same covered contract surface as QQ. No live send or receive evidence exists, and none is claimed. |
| Cron | `pico/proactive_engine/schedulers/cron/service.py` | V-D0 Cron subset; V-C0 covers Cron delivery resolution; V-LF covers real Feishu delivery | deterministic, live | Job persistence, fire claiming, dedup, survival across a process restart, and the failed/cancelled/expired/incompatible terminal diagnostics are verified offline. V-LF additionally records one real Feishu one-shot job executing exactly once after a Gateway restart. |
| Tracing | `pico/tracing/trace.py`, `pico/tracing/semconv.py`, `pico/tracing/spans.py` | V-TE0 (`make verify-turn-evidence`) | contract | One trace per Turn chains `spine.turn` to `session.turn` to its `llm.call` and `tool.call` spans, validated against `specs/turn-evidence-correlation.md`. Delivery spans and `DELIVERY_FAILED` notices join by trace and conversation. V-TE0 spends no live model calls and must not be reported as a live or production result. |
| Usage accounting | `pico/token_wise/usage_tracker.py`, `pico/token_wise/pricing.py`, `pico/tracing/usage.py` | V-TE0 | contract | Usage rows join their Turn by `trace_id` and `turn_span_id`, and a usage row pointing at a trace with no Turn is reported as a finding rather than passed over. The USD figure is an estimate computed from a local pricing table, not a billed amount from any Provider. |
| TokenWise cache placement | `pico/cli/_token_wise_stack.py`, `pico/token_wise/cache_optimizer.py` | TokenWise deterministic tests | deterministic, contract | The strategy implementation caps explicit cache breakpoints at four, but shared Runtime Assembly does not install it. The four-arm PicoBench cost contract is implemented, while its live runner and paid campaign have not run, so neither host activation nor a current cost reduction or cache hit-rate metric is eligible. |
| Agent task evaluation | `benchmarks/picobench/`, `benchmarks/picobench/suites/agent_application_ship_1.yaml` | PicoBench experiment `abffb7d2fe6a76f1102741cacd3cff1ed02697be0fb37fe2fa7a910dbeb11b4d` at clean source commit `e6c790e` | deterministic, live | The campaign recorded 216/216 terminal real-Provider Trials, 260/260 deterministic Retrieval Cases, 119/120 valid Pairs, and stable report digest `25ca985d2f80560fba789d14fc76acc07d0a45ea3b6a0b4aa7a3d4cfadf19eb1`. It is ship-complete but measurement-invalid because one Context Pair lacks complete usage evidence. Tool disclosure reduced estimated visible Schema tokens by 93.4513 percent across six measurable tasks but regressed task pass count from 23/24 to 20/24. No main-campaign positive metric is eligible. |
| CodeCairn task-effect v2 | `benchmarks/picobench/`, installed Pico and CodeCairn wheels | Issue #79 calibration experiment `6fbc169ee80ff29e7b8822e6a26992856706a69eab71853ba3e08338410ed11f` at Pico `d6ef624` and CodeCairn `555248e` | installed, live | The calibration recorded 12/12 terminal task Trials, 10/10 measurable Retrieval Cases, 0/6 valid Pairs, and report digest `a5e4f79acd756276eb1b714dfc7959ac0e1e84a209df60d7b8f916412e66cde3`. All task Trials were Provider failures, so measurement validity and every Claim Gate failed closed and the formal matrix did not run. This is campaign and Provider-boundary evidence, not CodeCairn task-effect evidence. |
| Historical semantic retrieval | `benchmarks/picobench/semantic_campaign.py`, `benchmarks/picobench/suites/agent_application_ship_1_semantic_v2.yaml` | semantic v2 experiment `98bb1e3cca2d1ee45dbebebef7f44db87fbea8ea23d1ea177843df6ba3ca2a1b` at clean source commit `e6c790e` | historical live | The addendum recorded 260/260 measurable held-out records, including 200 former production EverOS retrieval records and 60 Local-only BM25 controls. Its metrics remain eligible only for that historical implementation and are not relabeled as CodeCairn evidence. |
| Distribution | `hatch_build.py`, `scripts/verify_distribution.py`, `.github/workflows/release.yml` | V-P0 (`scripts/verify_distribution.py`) | contract | The exact wheel manifest is enforced, the base package and each retained extra install into separate environments, and the installed CLI, TUI, Gateway, help, and doctor paths are probed with an empty `PYTHONPATH` and no source checkout. A wheel rebuilt from the source distribution must match the directly built wheel file-for-file. The wheel embeds the compiled TUI bundle but not a Node.js runtime; Node.js 22 remains a host requirement. |
| Evolver | `pico/evolver/cli.py`, `pico/evolver/orchestrator/loop.py`, `pico/evolver/candidate_manifest.py`, `pico/evolver/activation/artifacts.py` | V-E0 (`make verify-evolver`) | deterministic | Beta and opt-in. Evidence is the deterministic fixture-backed cross-process Evolution Run plus the small real run recorded separately once it exists; the two are never merged into one number. V-E0 spends no live model calls and must not be reported as a benchmark or production result. Candidates require manual activation, runtime candidates require a Rollback Artifact by default, and no model-weight training is performed or claimed. |

## Beta surfaces

Beta names the evidence behind a surface, not its code quality.

| Surface | Why Beta | What would lift it |
| --- | --- | --- |
| QQ Channel | Deterministic contract evidence only (V-C0, V-S0) | A live Gate run against a real QQ bot, recorded per commit and scenario |
| WeCom Channel | Deterministic contract evidence only (V-C0, V-S0) | A live Gate run against a real WeCom bot, recorded per commit and scenario |
| Evolver | Deterministic fixture evidence only (V-E0) | A recorded small real Evolution Run, reported separately from V-E0 |

## Deferred and explicitly not claimed

These are absent by decision, not by oversight. Nothing in this repository
should be read as evidence for any of them.

| Item | Status |
| --- | --- |
| Model-weight training or fine-tuning | Not implemented. Model-weight files are forbidden by the Candidate Manifest allowlist. |
| Autonomous self-improvement | Not implemented. Promotion selects a baseline inside an Evolution Run; a runtime candidate starts `pending_human` and the activation record never edits a checkout or moves `HEAD`. |
| Production-verified QQ or WeCom | Deferred until a live Channel Gate passes for those adapters. |
| Remote Skill marketplace | Deliberately excluded. Only Local Skills are retrievable. |
| Non-target messaging Channels | Deliberately excluded. The retained adapters are Feishu, QQ, and WeCom. |
| Proactive Sentinel behavior | Deliberately excluded. Cron is user-scheduled, not self-initiated. |
| Media generation, Deep Research, MiroThinker | Deliberately excluded. Media input, attachment parsing, and `MediaOut` delivery remain supported. |
| PyPI publishing | Not wired up. The supported install path is the wheel attached to the GitHub Release. |
| External state migration | No implicit migration framework ships in v1. An explicit `--config` or `--workspace` path is the only opt-in seam. |
