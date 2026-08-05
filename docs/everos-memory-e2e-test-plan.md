# EverOS memory — extraction & retrieval E2E test plan

> Status: historical pre-CodeCairn verification plan. Current `main` no longer
> bundles EverOS, and the commands and test files named below have been removed.
> This document records the old Gate only; it is not a current release path or
> CodeCairn verification procedure.

This plan covered Pico's former bundled `EverosBackend` adapter over a real
`everos` Runtime. It validated dual-track recall (user-side memory +
agent-side skills) and whether memory extraction produced skills matching
expectations.

## Goals / acceptance criteria

1. **User-side recall** — storing a conversation with user facts makes
   `recall(user_id="…")` return episodes/profiles whose content
   matches the facts.
2. **Agent-side skill recall** — repeated task demonstrations are
   extracted and `recall(agent_id="…")` returns `agent_skill`(s).
3. **Skill matches expectation** — an extracted skill's
   `name`/`description`/`content` semantically match the demonstrated
   procedure, with `confidence`/`maturity_score ∈ [0,1]` and non-empty
   `source_case_ids`.
4. **Dual-track isolation** — a user query never surfaces agent skills;
   a call with neither or both track ids returns `[]`.
5. **Failure contract** — configured EverOS import, startup, recall, and
   persistence failures propagate; only `memory.backend = null` disables Memory.

## Hard constraints (from everos 1.1.2)

| Constraint | Fact | Test impact |
|---|---|---|
| Accumulate-then-extract | `memorize` returns `status ∈ {accumulated, extracted, skipped}`; extraction fires on a boundary (`hard_token_limit` / `hard_msg_limit`) or an `is_final=True` flush | A turn or two won't extract; tests must cross a boundary or flush |
| Skills cluster from cases | agent pipeline runs `trigger_skill_clustering` + `extract_agent_skill`; skills carry `maturity_score`, `source_case_ids` | The corpus must repeat the same procedure across sessions |
| Backend flush policy | `_RealEverosAdapter.memorize` forwards `is_final`; `flush_every_turns` defaults to one and zero disables automatic flushes | L2 forces `is_final`; L3 uses the production backend policy |
| LLM non-determinism | every `extract_*` calls a real LLM + embedding | Assertions are structural + semantic-keyword, never exact-string |
| Runtime deps | `EVEROS_LLM__*`, `EVEROS_EMBEDDING__*`, sqlite/lancedb under `EVEROS_ROOT` | Real LLM key required; store isolated to a temp dir |

### Search item fields (assertion targets — `everos.memory.search.dto`)

- user/episode: `summary, subject, episode, score, atomic_facts`
- user/profile: `profile_data (dict), score`
- agent/skill: `name, description, content, confidence, maturity_score, source_case_ids, score`
- agent/case: `task_intent, approach, quality_score, key_insight, score`

## Layers

| Layer | What | Where | LLM? |
|---|---|---|---|
| L1 | Backend translation (owner routing, message conversion, result flatten, failure propagation) | `tests/test_em2_backend.py`, `tests/test_em3_http.py` | no (fakes) — default CI |
| L2 | everos extraction quality — direct service + `is_final` flush | `tests/integration/test_everos_extraction_real_llm.py` | yes (`real_llm`) |
| L3 | backend ↔ everos e2e — embedded mode `store`/`recall` | `tests/integration/test_everos_backend_e2e.py` | yes (`real_llm`) |
| L4 | continuity across fresh processes, workspaces, and Session ids | `tests/integration/test_everos_continuity_real_llm.py` | yes (`real_llm`) |
| L5 | real Channel-shaped Memory Markdown and remembered-Skill evolution probes | `tests/integration/test_everos_channel_e2e.py`, `tests/integration/test_everos_skill_evolution_e2e.py` | yes (`real_llm`) |

### Skill-validation strategy (three tiers, increasing strictness)

1. **Structural** (always): fields present + typed; `confidence/maturity ∈ [0,1]`; `score > 0`; `source_case_ids` non-empty.
2. **Semantic keyword** (always): `name/description/content` hit the seeded keyword set (`expect_keywords` in the corpus).
3. **LLM-judge** (opt-in, `@pytest.mark.llm_judge`): an LLM grades whether the skill faithfully summarizes the demonstrated procedure. Closest to "matches expectation" but costly/noisy — kept out of the default `real_llm` set.

## Files

```
tests/integration/
  conftest.py                         # markers, everos_env (gating), ids, corpus, payload helper
  data/everos_skill_corpus.json       # user facts + repeated skill demonstrations + expect_keywords
  _everos_continuity_probe.py         # isolated subprocess store/recall driver
  test_everos_extraction_real_llm.py  # L2
  test_everos_backend_e2e.py          # L3
  test_everos_continuity_real_llm.py  # L4
  test_everos_channel_e2e.py           # L5
  test_everos_skill_evolution_e2e.py   # L5
docs/everos-memory-e2e-test-plan.md   # this file
```

## Fixtures / environment / gating

- `everos_env` (function): sets `EVEROS_ROOT` to a temp dir,
  `EVEROS_MEMORIZE__MODE=agent`, a tight `EVEROS_BOUNDARY_DETECTION__HARD_MSG_LIMIT`,
  passes only resolved Provider fields through environment variables,
  clears `load_settings` cache, and **skips** when everos / LLM key /
  embedding model are absent. It copies the bundled default OME policy,
  never the operator's credential-bearing config.
- `ids`: unique user / Agent / Session ids per test for isolation
  (everos service singletons are process-global; we partition by owner).
- `corpus`: loads the seed JSON. `as_everos_payload(...)` mirrors the
  backend's message conversion so L2 and L3 feed everos the same shape.

## How to run

```bash
# Canonical offline continuity layer
make verify-continuity-deterministic

# Canonical required deterministic + real cross-process continuity Gate
make verify-continuity

# Broader real EverOS diagnostics and extraction-quality probes
uv run pytest tests/integration -m real_llm -q -rs
```

Provider and embedding configuration must be supplied through the supported
operator environment or isolated Config. Never put keys in commands committed
to documentation, test output, or evidence artifacts.

## Risks / known gaps

1. **Non-determinism** — handled by the tiered assertions; the must-pass
   set uses only structural + keyword checks.
2. **Skill clustering latency** — even after a final flush, clustering
   can remain model-dependent; L3 keeps its pre-existing best-effort
   skill assertion while L2 owns the strict extraction-quality contract.
3. **Cost / latency** — `real_llm` tests are slow and billable; isolate to
   a dedicated CI job, never the default suite.
4. **Store pollution and evidence safety** — fixtures and the L4 probe
   force `EVEROS_ROOT` to a temp dir. The L4 artifact contains only
   status, counts, synthetic identifiers, and booleans; it never records
   prompts, recalled text, Provider URLs, environment variables, or keys.

## Naming compliance note (AGENTS.md §5.2)

The production socket smoke uses the ticket-free integration name
`tests/integration/test_tui_rpc_production_smoke.py`.
