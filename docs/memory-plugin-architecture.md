# Memory and Plugin architecture

> Status: current Pico implementation contract.

This document describes the public `MemoryBackend` Protocol, Plugin discovery,
Runtime lifecycle, and installed CodeCairn adapter. For the full state and
Context relationship, read
[State, Context, Memory, and Skills](architecture/state-and-intelligence.md).

## Design goals

1. Pico selects one repository-scoped CodeCairn Memory backend by default.
2. A user can explicitly disable Memory with `memory.backend = null`.
3. A selected backend fails visibly instead of silently losing recall or
   persistence.
4. Plugin discovery remains cheap and normally does not import heavy backend
   code.
5. Third-party backends and Tools use a narrow manifest/factory seam.
6. Local Skills and Sessions remain usable when Memory is disabled.
7. CodeCairn owns its journal, repository identity, import, ranking, packing,
   and index; Pico does not reimplement those responsibilities.

## MemoryBackend Protocol

`pico/memory_engine/backend.py` defines the structural Protocol:

```python
class MemoryBackend(Protocol):
    async def recall(
        self,
        query: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        top_k: int,
    ) -> list[Memory]: ...

    async def store(self, session_id: str, messages: list[dict]) -> None: ...
    async def feedback(self, signals: dict) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

The active Pico host calls `recall(..., user_id=...)` for the Context Memory
segment. The selected Workspace, not `user_id` or process cwd, determines the
initialized CodeCairn repository. Local Skill retrieval is independent of the
Memory backend, so the host does not use the Agent lane for remembered Skills
and does not dispatch backend feedback.

`agent_id` and `feedback()` remain in the structural Protocol for third-party
Plugin compatibility. A backend may return no Agent-lane hits. Pico does not
expose a third world-knowledge argument or add namespace prefixes to ids.

## Runtime construction and lifecycle

`pico/cli/_plugin_stack.py` and
`pico/cli/_runtime_assembly.py` divide ownership:

```text
build_plugin_registry()
  -> discover and activate manifests

maybe_build_memory_backend()
  -> resolve configured contribution
  -> build backend, not started

assemble_runtime()
  -> pass backend into Agent Loop and Context Engine
  -> return RuntimeAssembly

RuntimeAssembly.start_memory_backend()
  -> start once; cache and re-raise failure

RuntimeAssembly.close()
  -> close MCP/Agent resources
  -> stop backend and expose any stop failure after other cleanup
```

`memory.backend = null` returns no backend and is the only implicit-Memory
disable path. It invokes no backend factory, lifecycle, recall, store,
feedback, journal, importer, or index operation.

Selected backend behavior is fail-closed:

- missing contribution raises with installation remediation;
- factory, import, or configuration error raises;
- startup error raises;
- required recall or store error fails the Turn;
- shutdown continues other cleanup and then exposes the backend stop failure.

There is no production no-op or empty-Memory fallback. Plugin Tool
construction is intentionally different: one optional Tool factory may return
`None` or raise, and Pico logs and skips that Tool.

## Plugin discovery

`pico/plugin/discover.py` scans:

| Priority | Source | Location |
| ---: | --- | --- |
| 4 | bundled | `pico/plugin/memory/<plugin-id>/` |
| 3 | user | `~/.pico/plugins/<plugin-id>/` |
| 2 | project | `<process-cwd>/.pico/plugins/<plugin-id>/` |
| 1 | entry points | group `pico.plugins` |

The highest-priority manifest wins for one Plugin id. Different ids coexist.
A bundled Plugin cannot be shadowed by a user or third-party package with the
same id.

Directory sources parse `pico-plugin.toml` without importing implementation
code. Entry-point resource discovery can import the entry-point package, so
its top-level module must remain lightweight.

The project Plugin directory is based on process cwd, not the configured Agent
Workspace. CodeCairn repository binding does not use this discovery location;
the Adapter receives the configured Workspace through `PluginContext`.

## Manifest and factories

A Plugin manifest can contribute Memory backends and Tools:

```toml
[plugin]
id = "example-memory"
version = "1.0.0"
bundled = false

[[plugin.contributes.memory_backends]]
name = "example"
factory = "example_plugin.backend:make_backend"

[[plugin.contributes.tools]]
name = "example_tool"
factory = "example_plugin.tools:make_tool"
```

The factory receives `PluginContext`:

- `config`: the free-form slice from `plugins.config[plugin-id]`, falling back
  to the contribution name for Memory backends;
- `services`: a narrow locator containing the configured Workspace;
- `logger`: Plugin-scoped logger.

The manifest `config_schema` is metadata/passthrough. The Registry does not
perform general schema validation from it, so a backend must validate the
fields it consumes. Duplicate contribution names fail registry activation.
Plugins marked `enabled_by_default = false` are skipped.

## Installed CodeCairn Plugin

Pico's base distribution pins CodeCairn to the accepted immutable Git commit.
The installed distribution contributes these fixed public identifiers:

| Identifier | Value |
| --- | --- |
| entry-point group | `pico.plugins` |
| entry-point name | `codecairn` |
| resource package | `codecairn.integrations.pico` |
| manifest id | `codecairn-memory` |
| backend name | `codecairn` |
| factory | `codecairn.integrations.pico.backend:make_backend` |

The operator initializes the target Git repository explicitly:

```bash
codecairn init
```

Fresh Pico config selects:

```json
{
  "memory": {
    "backend": "codecairn",
    "memoryTopK": 5
  }
}
```

Pico has no CodeCairn runtime-root, repository, retrieval-profile, or
credential override. Those values remain in the CodeCairn configuration
selected by `codecairn init`.

At `start()`, the Adapter resolves the configured Pico Workspace, validates
the initialized Git repository and CodeCairn requirements, and imports any
durable journal suffix. Configuration, provider, journal, index, and identity
failures abort startup with remediation.

`recall()` returns one compiled, source-attributed Pico `Memory` for
repository-scoped context. Pico does not rerank or repack the result.
`store()` receives the same normalized after-Turn slice that Session
persistence accepted, without Runtime preambles or recovery scaffolding.
CodeCairn durably journals and imports that slice and returns only when the
write is recall-visible or fails. Blocking operations run off the host event
loop.

The former `memory.backend = "everos"` value is a migration error, not an
alias. Pico tells the operator to initialize CodeCairn and select
`codecairn`, or explicitly select `null`. It does not silently rewrite config,
read the removed backend's state, migrate it, or delete it. The removed
adapter and its `understand_media` Tool are not bundled in the Pico wheel.

## Adding a third-party Memory backend

Recommended distribution:

```text
pico-example-memory/
  pyproject.toml
  src/pico_example_memory/
    __init__.py
    backend.py
    pico-plugin.toml
```

Register a `pico.plugins` entry point, keep package import cheap, and expose a
factory returning a structural `MemoryBackend`. Installation in this
repository must use `uv`, for example:

```bash
uv add pico-example-memory
```

Backend rules:

- validate the Plugin Config it consumes;
- implement explicit start/stop;
- accept the public user/Agent-lane shape, returning no Agent hits if unused;
- propagate configured persistence failure;
- never import Pico CLI composition;
- test through the public Protocol and a real integration layer.

Drop-in user and project directories are also supported, but the operator must
make their Python dependencies available.

## Verification

Deterministic coverage includes:

- Runtime Assembly construction, lifecycle, and fail-closed behavior;
- Agent Loop normalized store-slice and Memory-off zero-call behavior;
- Local Skill parity with CodeCairn selected and with Memory off;
- generic third-party manifest, factory, and backend Protocol tests;
- installed CodeCairn entry-point and manifest discovery;
- wheel metadata and content checks rejecting bundled EverOS Runtime files or
  direct EverOS dependencies.

The installed integration smoke uses real CodeCairn in a temporary initialized
Git repository and verifies start, store, fresh recall, and stop without source
checkout leakage. It uses no local Adapter stub and makes no task-level
improvement claim.

Historical EverOS continuity and PicoBench reports remain evidence only for
their recorded commits and experiments. They are not relabeled as CodeCairn
proof.

## Known limitations

- no cross-domain transaction across Session, Curator, CodeCairn, and Tracing;
- Plugin `config_schema` is descriptive, not generally enforced;
- entry-point discovery may import a third-party package;
- project Plugin discovery uses process cwd;
- no remote Plugin or Skill marketplace;
- no automatic Memory deletion cascade when a Session is deleted;
- CodeCairn does not currently abstain on the frozen hard-negative queries, so
  the completed paired measurement is not eligible for a positive claim.
