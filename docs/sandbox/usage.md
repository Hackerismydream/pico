# Pico Sandbox usage

> Status: current contract for `pico-harness 0.1.7`.
>
> Pico does **not** run commands in a microVM by default. The default
> `backend = "none"` uses direct host execution. BoxLite is an explicit,
> fail-closed opt-in.

The Sandbox package gives Agent Tools one `SandboxExecutor` interface with two
implementations:

- `DirectExecutor`: host execution with a reduced inherited environment;
- `BoxliteExecutor`: one BoxLite microVM owned by an Agent Loop.

Application-level path checks, dangerous-command heuristics, timeouts, and
untrusted-content fencing complement these executors. They do not turn direct
host execution into OS isolation.

## Requirements

- Python 3.12 (`>=3.12,<3.13`);
- `uv` for repository dependency management;
- optional `boxlite==0.9.5` through the `sandbox` extra;
- for BoxLite:
  - Apple Silicon and a supported macOS release, or
  - Linux/WSL2 with usable KVM according to BoxLite requirements.

Install from a source checkout:

```bash
uv sync --extra sandbox
```

Verify the optional import:

```bash
uv run python -c "import boxlite; print(boxlite.__version__)"
```

Do not use `pip` to mutate this repository environment.

## Configuration

Sandbox Config lives under `tools.sandbox`:

```json
{
  "tools": {
    "sandbox": {
      "backend": "boxlite",
      "image": "ubuntu:22.04",
      "cpus": 2,
      "memoryMib": 2048,
      "diskSizeGb": null,
      "allowNet": false,
      "extraVolumes": [],
      "defaultTimeout": 120,
      "verifyTimeout": 30,
      "createTimeout": 300,
      "debug": {
        "enabled": false,
        "socket": "sandbox/debug.sock",
        "maxMessageBytes": 1048576
      }
    }
  }
}
```

| Field | Default | Meaning |
| --- | --- | --- |
| `backend` | `none` | `none`, `auto`, or `boxlite` |
| `image` | `ubuntu:22.04` | OCI image for the working VM |
| `cpus` | `2` | VM vCPU count |
| `memoryMib` | `2048` | VM memory |
| `diskSizeGb` | `null` | `null` uses BoxLite ephemeral default |
| `allowNet` | `true` | all network, no network, or domain allowlist |
| `extraVolumes` | `[]` | `[host_abs, guest_abs, "ro"|"rw"]` entries |
| `defaultTimeout` | `120` | default VM command timeout |
| `verifyTimeout` | `30` | startup `echo ok` timeout |
| `createTimeout` | `300` | image pull and VM creation timeout |
| `debug.enabled` | `false` | start the Unix-socket debug server |
| `debug.socket` | `sandbox/debug.sock` | absolute path or path relative to Pico data dir |
| `debug.maxMessageBytes` | `1048576` | protocol line limit |

`allowNet: []` is rejected as ambiguous. Use `false` for no network.
Volume host and guest paths must both be absolute.

## Backend selection

### `none`

`none` returns `DirectExecutor`. Pico logs one warning per process:

- Agent commands run on the host;
- prompt-injected commands have host authority;
- no microVM exists;
- Sandbox debug mode has no VM to inspect.

This is the current default.

### `auto`

`auto` currently has one candidate backend: BoxLite. It:

1. imports BoxLite;
2. constructs `BoxliteExecutor`;
3. creates and probes the VM during executor startup.

If any step fails, Pico raises `SandboxInitError`. `auto` does **not** fall back
to `DirectExecutor`. The name means automatic BoxLite availability detection,
not best-effort isolation.

### `boxlite`

`boxlite` has the same availability and startup behavior as `auto`, but makes
the operator intent explicit. Missing extra, unsupported host, image failure,
VM creation timeout, or failed startup probe is a visible startup failure.

Use `none` explicitly if host execution is acceptable. Do not recover from a
requested Sandbox failure by silently changing the backend.

## Executor lifecycle

Agent Loop constructs one executor and starts it before Tool execution.

```text
AgentLoop
  -> build_executor(Config, Workspace)
  -> executor.start()
  -> ExecTool and compatible MCP use executor
  -> executor.stop() during Runtime close
```

Subagents receive their own executor instances and remain subject to Subagent
concurrency/rate limits.

`SandboxExecutor` exposes:

```python
async exec(command, cwd=None, timeout=None, env=None) -> ExecResult
async start()
async stop()
async start_process(command, args, env=None)  # only supported implementations
```

`ExecResult` contains `stdout`, `stderr`, and `exit_code`. Timeout returns
`exit_code = -1` with a timeout diagnostic.

## DirectExecutor

Direct mode uses `asyncio.create_subprocess_shell`.

### Environment

It inherits a small allowlist:

- shell, locale, user, temporary-directory, and terminal basics;
- Python/virtual-environment path;
- TLS trust and proxy configuration;
- Windows process/runtime basics where applicable.

Cloud credentials, API keys, SSH variables, and arbitrary parent environment
variables are not inherited unless the caller explicitly supplies them.
Explicit Tool environment still grants those values to the child process.

### Timeout

The direct executor caps a single command at 600 seconds even if a larger
timeout is requested. On timeout it kills the process and returns a failed
result.

### Guardrails

When execution is not sandboxed, `ExecTool` applies its dangerous-command
checks. Workspace restriction can also reject paths outside the configured
Workspace.

These controls are heuristic:

- shell syntax has many equivalent forms;
- a permitted interpreter can perform arbitrary I/O;
- path checks are not a kernel namespace;
- the process runs as the Pico user.

Treat direct mode as host execution.

## BoxliteExecutor

BoxLite uses one working microVM per executor.

### Workspace and volumes

- configured Workspace mounts read/write at `/workspace`;
- commands default to `/workspace`;
- extra volumes require explicit absolute host and guest paths;
- each extra volume declares `ro` or `rw`.

The Workspace mount means candidate or Tool code can modify everything in that
Workspace. Do not point it at a sensitive directory merely because the process
runs in a VM.

### Network

- `true`: unrestricted VM network;
- `false`: no VM network;
- `["example.com", ...]`: BoxLite domain allowlist.

For restricted networking, Pico pre-pulls the image through a short-lived
unrestricted Box before creating the working VM with the configured policy.
This avoids requiring registry access from the restricted VM.

Domain policy is only one layer. Verify DNS, redirects, proxies, and target
application behavior for high-risk workloads.

### Startup

`start()`:

1. optionally pre-pulls the image;
2. creates the VM within `createTimeout`;
3. registers cleanup before boot;
4. starts the VM;
5. runs `echo ok` within `verifyTimeout`.

Any partial-start failure triggers cleanup before the error propagates.

### Command execution

Commands run through `sh -c` with a translated VM working directory. Output
streams are collected and returned as one `ExecResult`. Timeout attempts to
kill the BoxLite execution.

The host dangerous-command regex is skipped for a Sandbox reporting real
isolation. Workspace restrictions still apply at the Tool layer.

### MCP stdio

`BoxliteExecutor` supports long-running process spawning and bridges MCP stdio
streams. A configured stdio MCP server that cannot run through the selected
Sandbox fails closed rather than moving to an unsandboxed host process.

HTTP/SSE MCP connections are network clients and follow their own transport and
network controls.

## Agent Tool integration

`pico/agent/tools/shell.py::ExecTool` holds only `SandboxExecutor`; it does not
import BoxLite.

Tool execution:

1. validate command and Workspace policy;
2. call executor with working directory, timeout, and explicit environment;
3. convert stdout/stderr/exit code to a `ToolResult`;
4. mark nonzero exit or timeout as a failed Tool event;
5. fence untrusted output before returning it to the model.

A failed Tool result normally remains inside the Turn so the model may recover.
Sandbox initialization failure happens earlier and fails the Turn/host.

## Debugging a Runtime-owned VM

Enable:

```json
{
  "tools": {
    "sandbox": {
      "backend": "boxlite",
      "debug": {
        "enabled": true
      }
    }
  }
}
```

Then keep `pico run`, TUI, or Gateway running and use:

```bash
pico sandbox list
pico sandbox exec [--vm ID_OR_NAME] uname -a
pico sandbox shell [--vm ID_OR_NAME] --shell /bin/sh
```

Properties:

- Unix socket mode `0600`;
- one active debug client at a time;
- a VM must be owned by the connected Pico process for exec/shell;
- omitting `--vm` works only when exactly one owned running VM exists;
- protocol resolution accepts exact VM id or name;
- an existing live socket prevents a second Pico process from stealing the
  same debug path.

The current `list` CLI table displays id, state, image, CPU, memory, and
creation time. The protocol can resolve a VM name even though the table does
not currently show a Name column.

See [Debug commands](debug_commands.md).

## Direct BoxLite administration

`scripts/boxlite_cli.py` talks to the BoxLite library directly. It can:

- list, pull, and remove images;
- create, start, stop, list, remove, and shell into VMs;
- target Pico's BoxLite home or another BoxLite home;
- work while no Agent debug server is running.

It is different from `pico sandbox`:

| Tool | Scope |
| --- | --- |
| `pico sandbox` | VMs owned by one live Pico process through its debug socket |
| `scripts/boxlite_cli.py` | direct BoxLite runtime administration |

See [BoxLite CLI](boxlite_cli.md).

## Security guidance

### Direct mode

- assume full Pico-user host authority;
- use a disposable Workspace;
- keep secrets out of explicit Tool environment;
- enable `restrictToWorkspace` where compatible;
- require confirmation for risky operations;
- do not call it isolated.

### BoxLite mode

- mount only the required Workspace and volumes;
- prefer read-only extra volumes;
- set `allowNet: false` or the smallest domain list;
- use scoped credentials;
- use disposable VMs and Workspaces;
- remember that VM code can still damage read/write mounts and reachable
  services.

### Evolver

Evolver candidates run under the benchmark scorer's authority. Path guards and
beacons prevent common shortcut classes but do not defend against malicious
code. Run the designer, subject, and scorer in a disposable outer container or
VM with scoped credentials. The ordinary Agent Sandbox is not by itself an
adversarial evaluation boundary.

## Testing

Deterministic Sandbox tests:

```bash
uv run pytest \
  tests/test_sandbox_unit.py \
  tests/test_sandbox_debug_server.py \
  tests/test_cli_sandbox_commands.py \
  tests/test_mcp_sandbox.py \
  -q
```

Discover current Sandbox-related files before narrowing a command:

```bash
find tests -type f -name '*sandbox*' -print
```

Real VM tests use the `real_vm` marker and are opt-in:

```bash
uv run pytest -m real_vm -q -rs
```

Missing BoxLite/KVM is a skip in optional diagnostic runs. A release or issue
Gate that declares real VM behavior required must convert skip, infrastructure
failure, and inconclusive execution into a failed Gate.

Do not freeze test counts in this manual; counts belong to commit-bound
evidence.

## Troubleshooting

### `No sandbox backend available`

The selected backend requires BoxLite but the extra is absent:

```bash
uv sync --extra sandbox
```

If the host cannot run BoxLite, explicitly choose `none` only after accepting
host execution.

### VM creation or verification timeout

- verify host resources and KVM/virtualization support;
- verify registry connectivity;
- pre-pull the image with `scripts/boxlite_cli.py`;
- increase `createTimeout` or `verifyTimeout` only after measuring the slow
  operation;
- inspect and clean partial VMs through the direct BoxLite CLI.

### Debug socket missing

- confirm a Pico Agent process is still running;
- confirm backend is not `none`;
- confirm `debug.enabled` is true in the config that process loaded;
- resolve the socket relative to the active Pico data directory;
- inspect Runtime logs for a bind conflict.

### MCP stdio fails in Sandbox

- verify the command and binary exist inside the VM image;
- mount required files;
- pass only required environment;
- verify the selected executor supports process spawning;
- do not recover by launching the server unsandboxed without an explicit
  operator decision.

## Known limitations

- default execution is not isolated;
- `auto` has no alternative backend or direct fallback;
- Workspace restriction and command filters are heuristic;
- no Windows-native BoxLite contract is verified by Pico release evidence;
- no persisted outbound relationship exists between VM work and Channel
  delivery;
- debug server is Unix-socket and single-client;
- VM lifecycle is tied to the Agent Loop, not a durable job scheduler;
- real VM checks are not part of the default deterministic suite.
