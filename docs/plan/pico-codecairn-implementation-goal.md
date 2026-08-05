# Codex Goal: ship Pico's CodeCairn Memory implementation

Status: completed by PR #68. The delivery contract below intentionally records
the pre-Issue #70 boundary in which `codecairn-003` was still blocked; current
joint evidence status is in
[`pico-codecairn-joint-evidence-goal.md`](pico-codecairn-joint-evidence-goal.md).

## Objective

Consume the installed CodeCairn Memory adapter, make it Pico's default
long-term Memory backend, and remove active EverOS product coupling while
preserving Pico Runtime, Session, Context, Local Skills, Tool/MCP, Plugin
extensibility, and historical evidence.

The user-facing result is:

```json
{
  "memory": {
    "backend": "codecairn"
  }
}
```

`memory.backend = null` remains the only Memory-off path. Pico must not retain
EverOS as a fallback or operate both backends.

## Preconditions

Do not invent a local CodeCairn stub or source-path dependency. Start code work
only after the CodeCairn repository provides the completed `v02-002` handoff:

- merged CodeCairn commit;
- canonical immutable `install_spec`;
- distribution name and version;
- wheel filename and SHA-256;
- plugin entry-point inventory;
- installed Pico contract-smoke result.

If that handoff is absent or inconsistent with the fixed identifiers below,
report the exact blocker and do not create a compatibility layer.

## Authoritative context

Read these files before editing:

1. `AGENTS.md`
2. `CONTEXT-MAP.md`
3. `CONTEXT.md`
4. `docs/INDEX.md`
5. `docs/specs/codecairn-memory-backend.md`
6. `docs/plan/analysis/codecairn-memory-replacement.md`
7. `docs/plan/tasks/codecairn-001.md`
8. `docs/plan/tasks/codecairn-002.md`

The two task files own detailed paths, Gates, deletion inventory, and exit
criteria. This Goal owns their authorization sequence, merge order, and
handoff to joint verification.

## Fixed cross-repository identifiers

| Contract | Value |
| --- | --- |
| Pico entry-point group | `pico.plugins` |
| Entry-point name | `codecairn` |
| Resource package | `codecairn.integrations.pico` |
| Plugin manifest ID | `codecairn-memory` |
| Memory backend contribution | `codecairn` |
| Backend factory | `codecairn.integrations.pico.backend:make_backend` |
| Source schema | `codecairn.pico.source.v1` |
| Turn boundary | `pico_turn_end` |

Changing any identifier requires an explicit cross-repository contract change.
Do not solve a mismatch with aliases or fallback discovery.

## Authority setup

Before implementation:

1. create or confirm one GitHub delivery issue covering exactly
   `codecairn-001` and `codecairn-002`;
2. record the exact CodeCairn distribution identity, Provider/model as not
   applicable, and a paid-spend ceiling of CNY 0 in that issue;
3. write the issue number into both task cards' `authority-issue`;
4. enumerate the exact EverOS callers, configuration, package, Skill, tests,
   and docs whose deletion Delivery 2 will own;
5. move only the dependency-satisfied task to `ready`.

The issue does not authorize `codecairn-003`, paid evaluation, V-R0, or a
formal Pico release.

## Delivery sequence

Implement the work as two serial, independently reviewable deliveries from the
latest `main`.

### Delivery 1: `codecairn-001`

Implement `docs/plan/tasks/codecairn-001.md` using the exact CodeCairn handoff.

Required outcome:

- add the compatible CodeCairn distribution through `uv`;
- fresh Pico config selects `codecairn`;
- no Pico-side CodeCairn runtime-root, repository, profile, or credential
  override is introduced;
- onboarding requires explicit `codecairn init`;
- missing plugin, missing initialization, identity mismatch, configuration,
  provider, journal, and index failures fail closed with remediation;
- Runtime Assembly starts and stops one adapter across CLI, TUI, and Gateway;
- `MemoryBackend.stop()` failure is exposed after other teardown completes;
- backend `store()` receives the same Session-normalized slice that Pico
  persisted, without Runtime preambles or recovery scaffolding;
- synchronous CodeCairn operations do not block the host event loop;
- repository binding follows Pico Workspace even when process cwd differs;
- Memory-off invokes no CodeCairn factory, lifecycle, recall, store, feedback,
  journal, importer, or index operation.

Run the task's M0/M1 checks and all affected Runtime, Plugin, Session,
configuration, CLI/TUI/Gateway, and packaging tests. Commit, self-review,
create the PR, wait for required checks, and squash-merge it before Delivery 2.

The Delivery 1 PR must include the post-merge planning state:

1. mark `codecairn-001` completed;
2. confirm the authority issue contains the accepted deletion inventory;
3. mark `codecairn-002` ready;
4. synchronize `docs/plan/tasks/README.md`, `docs/plan/README.md`, and the task
   cards.

Do not merge that PR until its Gates pass. The squash merge makes the
implementation and these state transitions true atomically.

### Delivery 2: `codecairn-002`

Create the second delivery from the updated `main`, then implement
`docs/plan/tasks/codecairn-002.md`.

Required outcome:

- delete the bundled EverOS Memory plugin and direct dependency;
- remove EverOS configuration mutation, onboarding, and active Runtime paths;
- remove EverOS remembered-Skill source, fusion weights, and feedback routing;
- remove `understand_media`, which has no CodeCairn replacement in this scope;
- preserve Local Skills and their BM25 behavior with CodeCairn on and Memory
  off;
- preserve the generic third-party `MemoryBackend` Plugin Interface;
- keep dated EverOS artifacts and donor evidence unchanged but explicitly
  historical;
- ensure the installed Pico wheel has no active EverOS package coupling;
- make old `memory.backend = "everos"` fail with actionable migration to
  `codecairn` or `null`, without silently rewriting operator data.

Run the task's M3 checks, affected product tests, distribution verification,
and `make check-large-files`. Use `uv` for every dependency change.

The Delivery 2 PR must include the post-merge planning state:

1. mark `codecairn-002` completed;
2. keep `codecairn-003` blocked;
3. synchronize `docs/plan/tasks/README.md`, `docs/plan/README.md`, and the task
   cards with the Pico-side implementation-complete, joint-unverified state.

Do not merge that PR until its Gates pass. The squash merge makes the
implementation and these state transitions true atomically.

## Required Pico handoff

After Delivery 2, produce a concise machine-readable or structured handoff for
the joint evidence task containing:

- `schema_version = 1`;
- `kind = "pico.codecairn.implementation.handoff"`;
- Pico commit and wheel SHA-256;
- canonical CodeCairn `install_spec`;
- CodeCairn version and wheel SHA-256 consumed;
- plugin and backend inventory;
- normalized store-slice contract result;
- Memory-off zero-call result;
- Local Skill parity result;
- installed distribution result;
- known limitations and any remaining non-EverOS Memory findings.

This handoff combines package and deterministic integration evidence. It does
not claim that CodeCairn improves task success.

Write it to:

```text
.pico/evidence/codecairn/<pico-commit>/handoff.json
```

The generated artifact is ignored and must not be committed. Copy its redacted
summary and SHA-256 into the final Goal response.

Generate the authoritative Pico handoff only after Delivery 2 squash-merges:

1. fetch the final `origin/main` and freeze its 40-character commit;
2. use a clean checkout at exactly that commit;
3. rebuild the Pico wheel and rerun the installed deterministic integration
   checks;
4. write `handoff.json` under the final commit directory.

A pre-squash feature-branch commit is not a valid joint-verification identity.
If the post-merge checks fail, fix them through a new reviewed PR before
declaring this Goal complete.

## Hard constraints

- Do not modify the CodeCairn repository from this Goal.
- Do not reimplement CodeCairn journal, import, ranking, packing, or repository
  identity in Pico.
- Do not add EverOS fallback, dual write, automatic migration, or hidden
  compatibility mode.
- Do not remove Pico Local Skills.
- Do not create another Agent Loop, Context Engine, Session, or evaluation
  framework.
- Do not reinterpret old EverOS PicoBench artifacts as CodeCairn evidence.
- Do not begin `codecairn-003` or CodeCairn `v02-003`.
- Do not initiate a paid provider campaign.
- Do not label this milestone as formal Pico v1, V-R0 completion, or a package
  semver release.

## Definition of done

This Goal is complete only when:

1. the exact CodeCairn adapter is consumed from its immutable `install_spec`;
2. `codecairn-001` and `codecairn-002` are merged serially to Pico `main`;
3. fresh config selects `codecairn`;
4. active EverOS Runtime, dependency, onboarding, and remembered-Skill
   coupling are absent;
5. Local Skills and the generic Memory Plugin contract remain green;
6. Memory-off zero-call and fail-closed startup behavior pass;
7. fresh installed Pico packages the intended dependency and discovers the
   CodeCairn backend without source-checkout leakage;
8. all focused and required repository checks pass;
9. the final handoff fixes the install specification and both built-wheel
   identities for joint verification;
10. `codecairn-003` remains blocked until the two repositories deliberately
    start the joint installed and paired-evidence campaign.

Do not stop after changing the default, passing a mocked backend test, or
opening a PR. Finish both develop-review-merge cycles and return a joint-test
ready Pico artifact. Report the result as "Pico-side implementation complete
and joint-test ready"; the end-to-end replacement remains unverified until
`codecairn-003` closes M2 and M4.
