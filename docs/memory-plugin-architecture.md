# Memory and Plugin architecture

Pico owns the Agent Harness and the generic `MemoryBackend` Interface. Myna
owns durable Memory, repository identity, source capture, indexing, recall,
and its operator-facing application. The integration is an installed public
Plugin seam; neither product vendors or privately imports the other.

## Runtime contract

`pico.memory_engine.backend.MemoryBackend` is the complete host contract:

```python
async def start() -> None: ...
async def recall(query, *, user_id=None, agent_id=None, top_k=5) -> list[Memory]: ...
async def store(session_id, messages) -> None: ...
async def feedback(signals) -> None: ...
async def stop() -> None: ...
```

Before each Turn, the Context Memory segment calls `recall()` and injects only
the returned `Memory.text`. After a persisted Turn, Agent Loop calls `store()`
with the normalized Session slice. Exceptions are not converted into empty
results or successful writes. `memory.backend = null` bypasses Plugin lookup
and preserves Sessions and Local Skills.

## Installed Myna Plugin

Pico discovers Myna through installed distribution metadata and the public
`pico.plugins` entry-point group.

| Field | Required value |
| --- | --- |
| distribution | `myna-memory` |
| entry point | `myna = myna.integrations.pico` |
| manifest | `myna/integrations/pico/pico-plugin.toml` |
| Plugin id | `myna-memory` |
| compatible Pico | `>=0.1,<0.2` |
| Memory backend | `myna` |
| factory | `myna.integrations.pico:make_backend` |

Discovery reads the manifest from the owning distribution file inventory. It
checks distribution name and version against the manifest and checks the
manifest's Pico version interval without importing the factory module. Invalid
identity or compatibility fails closed with remediation. Registry admission
validates contribution conflicts and records unresolved factory references;
the selected backend factory resolves only when Pico constructs that backend.

Discovery, admission, and `pico plugins` do not import the Myna package. Backend
construction imports only the declared public factory. Calling Myna's public
`descriptor()` separately is the point where the App descriptor and its
consent-bound setup contract load. Pico does not embed the Myna Local App or
Hub in this integration.

## Configuration and first use

Fresh Pico configuration selects:

```json
{
  "memory": {
    "backend": "myna",
    "userId": "default",
    "memoryTopK": 5
  },
  "plugins": {
    "disabled": [],
    "config": {}
  }
}
```

Myna configuration is not duplicated under Pico's `plugins.config`. From the
target Git repository, initialize the Myna-owned binding explicitly:

```bash
myna init
```

Pico never silently initializes Myna, scans agent history, imports historical
sessions, migrates prior data, or rewrites a retired backend selection. An
uninitialized repository, repository mismatch, degraded index, or journal
failure aborts the Memory lifecycle with a Myna remediation command.

## Ownership and persistence

Pico Session JSONL remains transcript truth. Myna's append-only Pico Source
Journal records accepted after-Turn slices under the Myna runtime root, imports
them through Myna's public application contract, and returns source-linked
Recall Context. A `pico_turn_end` source boundary says that a slice ended; it
does not assert that the task succeeded.

Session persistence and Myna persistence are separate failure domains. A
Session save can precede a failed Myna store. Pico reports that failure rather
than claiming an atomic cross-product transaction.

## Verification boundary

The installed composition Gate builds a Pico wheel, installs that wheel and a
frozen Myna wheel into an isolated Python 3.12 environment, and verifies:

- distribution and manifest identity;
- compatibility rejection before activation;
- discovery without source-checkout imports;
- explicit Memory-off behavior;
- uninitialized and degraded failure paths;
- store followed by recall in a fresh process;
- `myna://` source provenance and unrelated-query abstention.

These checks establish the package and lifecycle contract only. They are not
Pico task-effect, latency, cost, reliability, or production-success evidence.
