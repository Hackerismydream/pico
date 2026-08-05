# Pico

Pico is a compact Agent Harness for running reliable, tool-using agents across
the terminal, background services, scheduled jobs, and messaging channels.
Every entry point shares one Runtime, so Sessions, Context, Memory, Tools, and
Tracing stay continuous as work moves between surfaces.

Pico is a general Agent Harness, not a Coding Agent. Its optional Evolver
creates reviewable candidates and evaluation evidence, but never activates a
candidate without an explicit human decision.

[中文说明](README.zh-CN.md)

## Why Pico

- **One Runtime:** CLI, native TUI, Gateway, Cron, and Channels submit the same
  Turn contract through the Spine.
- **Durable context:** Sessions persist as JSONL, Context is budgeted before
  each model call, and CodeCairn provides repository-scoped Memory through the
  public Plugin interface.
- **Controlled tools:** Filesystem, Shell, Web, MCP, messaging, and Subagent
  Tools share confirmation, Sandbox, and tracing boundaries.
- **Evidence before claims:** deterministic checks, live integrations,
  infrastructure failures, and inconclusive results remain separate.
- **Human-controlled evolution:** candidates carry manifests, evaluations,
  verdicts, activation decisions, and rollback evidence.

## Quick start

Pico requires Python 3.12, `uv`, and Node.js 22 for the native TUI.

```bash
git clone https://github.com/Hackerismydream/pico.git
cd pico
make install build-tui
uv run pico onboard
uv run pico
```

Run one Turn without opening the TUI:

```bash
uv run pico run -m "Summarize this project"
```

Diagnose configuration or Provider problems:

```bash
uv run pico doctor
```

For an already-built release wheel:

```bash
uv tool install /path/to/pico_harness-0.1.7-py3-none-any.whl
pico onboard
cd /path/to/your-project
pico
```

## Main commands

| Goal | Command |
| --- | --- |
| Open the native TUI | `pico` |
| Start an interactive Session | `pico run` |
| Execute one Turn | `pico run -m "..."` |
| Configure Pico | `pico onboard` |
| Check local readiness | `pico doctor` |
| Inspect Runtime status | `pico status` |
| Manage Providers | `pico provider ...` |
| Manage Feishu, QQ, and WeCom | `pico channels ...` |
| Run the background Gateway | `pico gateway` |
| Manage Sessions | `pico sessions ...` |
| Manage scheduled work | `pico cron ...` |
| Browse local Skills | `pico skills ...` |
| Inspect Plugins | `pico plugins ...` |
| Open Tracing | `pico tracing` |
| Run opt-in evolution | `pico evolve check\|run\|status\|finalize` |

## Runtime model

```text
CLI / TUI / Gateway / Cron / Channel
                  |
                Spine
                  |
             Turn Runner
                  |
             Agent Loop
        / Context / Memory \
      Tools             Providers
                  |
          Session + Tracing
                  |
               Delivery
```

The Context Engine retrieves and budgets relevant state instead of blindly
truncating old messages. Local Skills remain available when Memory is disabled.
CodeCairn owns its repository binding and storage; Pico consumes it through the
installed Memory Plugin contract.

Feishu is live-gated against the configured Pico bot. QQ and WeCom are Beta and
have deterministic contract coverage without a current live send/receive
claim. Evidence applies only to the commit and scenario recorded by its Gate.

## State and security

| Scope | Default location |
| --- | --- |
| Global configuration and Runtime data | `~/.pico` |
| Foreground project | Current directory |
| Foreground project state | `~/.pico/projects/<project-id>` |
| Gateway Workspace | `~/.pico/workspace` |
| CodeCairn repository binding | CodeCairn configuration selected by `codecairn init` |

`PICO_HOME` relocates Pico's global root. Project state stays outside the
repository, so normal startup does not dirty Git or trust repository-controlled
bootstrap files. An explicit `--workspace` or `--config` path opts into direct
operation on that location.

## Development

```bash
make install
make ci
```

Start with the [documentation index](docs/INDEX.md),
[architecture overview](docs/architecture/README.md), and
[developer guide](docs/dev.md). Current capability claims and their evidence
classes are listed in [feature evidence](docs/feature-evidence.md) and
[project status](docs/project-status.md).

Pico is pre-1.0. Interfaces may change, and surfaces explicitly marked Beta
remain subject to tighter validation before release. `make ci` is the fast
development gate, not the complete release acceptance Gate.

## License

Pico is distributed under the Apache License 2.0. See [LICENSE](LICENSE),
[NOTICES.md](NOTICES.md), and [LICENSES/](LICENSES/) for authoritative license
and third-party attribution information.
