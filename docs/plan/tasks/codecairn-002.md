---
id: codecairn-002
scope: memory
status: completed
depends-on:
  - codecairn-001
authority-issue: 65
external-depends-on: []
gates: [M3]
requires-live-provider: false
---

# Remove EverOS product coupling and preserve Local Skills

## Objective

Complete the backend replacement instead of retaining two active Memory
products. Remove bundled EverOS code, dependency, onboarding, and remembered
Skill coupling while preserving Pico Sessions, Context, Local Skills, Plugin
extensibility, and historical evidence.

GitHub Issue #65 authorized the exact deletion inventory. Delivery 1 completed
first; this task is the serial Pico-side replacement delivery.

## Owned Pico paths

Expected scope:

```text
pico/plugin/memory/everos/
pico/config/update_everos.py
pico/config/pico.py
pico/config/loader.py
pico/memory_engine/skill_forge/
pico/cli/
pico/templates/
pyproject.toml
uv.lock
tests/
docs/
```

Dependency changes use `uv`; the lockfile is never edited by hand.

## Path

1. Enumerate every EverOS import, config field, template, command, Tool,
   Skill source, test, and package-data entry.
2. Delete the bundled `everos-memory` Plugin and direct EverOS dependency.
3. Remove `understand_media`; it has no CodeCairn replacement in this scope.
4. Remove EverOS configuration mutation and onboarding.
5. Remove the EverOS remembered-Skill source, weights, feedback routing, and
   misleading user controls.
6. Keep Local Skills and their BM25 behavior available with CodeCairn on and
   with Memory off.
7. Preserve the generic third-party `MemoryBackend` Plugin Interface.
8. Update current docs to CodeCairn while leaving dated EverOS evidence,
   donor baselines, and experiment reports unchanged.
9. Verify the wheel contains no bundled EverOS Plugin and no direct EverOS
   dependency.
10. Document that operator EverOS data is neither read nor deleted.

## Acceptance

- repository search finds EverOS only in explicitly historical/provenance
  files or migration notes accepted by the implementation issue;
- fresh config and onboarding contain no EverOS selection;
- Local Skills pass with `memory.backend = null` and `codecairn`;
- no current Runtime path imports or configures EverOS;
- third-party Memory Plugin tests remain green;
- V-P0 proves the Pico wheel is free of EverOS package coupling;
- M3 passes.

This task does not rewrite old PicoBench results as CodeCairn evidence.
