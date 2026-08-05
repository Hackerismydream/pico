---
id: codecairn-001
scope: memory
status: completed
depends-on: []
authority-issue: 65
external-depends-on:
  - codecairn:v02-001
  - codecairn:v02-002
gates: [M0, M1]
requires-live-provider: false
---

# Consume the CodeCairn Memory Adapter

## Objective

Make an installed CodeCairn Plugin the selected Pico Memory backend and expose
one fail-closed operator path:

```text
codecairn init
  -> memory.backend = codecairn
  -> Pico Runtime startup
```

GitHub Issue #65 supplies implementation authority. The consumed CodeCairn
handoff pins `e993eb562cf1bb0b89490de4e91c2a56d79eb3be`.

## Owned Pico paths

Expected scope:

```text
pico/config/pico.py
pico/config/update.py
pico/cli/_plugin_stack.py
pico/cli/_runtime_assembly.py
pico/cli/onboard_commands.py
pico/agent/loop/main.py
pico/templates/
pyproject.toml
uv.lock
tests/test_plugin_bootstrap.py
tests/test_cli_runtime_assembly.py
tests/test_config*.py
tests/test_product_identity.py
```

Exact onboarding test ownership must be confirmed against the implementation
issue before editing.

## Path

1. Add a compatible CodeCairn build to Pico's base distribution through `uv`;
   do not make the fresh default depend on an optional missing extra.
   Consume the canonical `install_spec` from the CodeCairn handoff. Before a
   registry release exists, it must pin the exact 40-character Git revision;
   local paths and floating branches are forbidden.
2. Change the fresh-config Memory default from `everos` to `codecairn`.
3. Keep the first Pico-side CodeCairn Plugin config empty. Resolve runtime root,
   repository binding, retrieval profile, and credentials only through the
   CodeCairn configuration selected for the granted Workspace.
4. Preserve `memory.backend = null` as an explicit Memory-off path.
5. Require entry point `codecairn`, Plugin id `codecairn-memory`, and backend
   contribution `codecairn`; do not add a
   source-tree CodeCairn import.
6. Replace EverOS onboarding with instructions to run `codecairn init` in the
   selected Git repository.
7. Surface missing initialization, invalid profile, provider/index failure,
   and missing Plugin as startup errors with remediation.
8. Verify Runtime Assembly starts and stops one Adapter across CLI, TUI, and
   Gateway composition.
9. Make Runtime Assembly finish all teardown and then expose
   `MemoryBackend.stop()` failure as a host shutdown failure rather than only a
   log entry.
10. Derive the backend `store` slice from the same Session-normalized messages
    that were persisted. Runtime-only context tags, recovery scaffolding, and
    rejected fields must not enter the CodeCairn Source Journal.
11. Add a heartbeat test proving synchronous CodeCairn work is dispatched off
   the host event loop.
12. Test with process cwd different from the configured Pico Workspace and
    prove CodeCairn binds the Workspace repository.

## Acceptance

- a clean base installation contains a compatible CodeCairn distribution and
  discovers entry point `codecairn`, Plugin `codecairn-memory`, and backend
  contribution `codecairn`;
- initialized repository startup succeeds;
- every named invalid setup fails closed;
- Memory-off performs zero CodeCairn factory, lifecycle, recall, store,
  feedback, journal, import, and index calls; discovery may still import the
  cheap entry-point package;
- a recording backend receives the same normalized user and Tool message view
  persisted in Session, with no Runtime-only context tag;
- backend stop failure is observable by each host after other teardown;
- repository binding uses Pico Workspace rather than process cwd;
- default host construction never falls back to EverOS or a no-op backend;
- Plugin and backend identifiers match the cross-repository contract;
- M0 and M1 pass.

This task does not delete EverOS yet and does not claim fresh-process recall or
task uplift.
