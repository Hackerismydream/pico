# Pico TUI

The React and Ink terminal frontend launched by `pico`. The Python Runtime
owns sessions, turns, tools, memory, model configuration, and persistence. The
Node process renders the conversational interface and communicates with the
Runtime only through the JSON-RPC socket in `pico/tui_rpc/`.

## Supported surface

- chat streaming, reasoning, expandable Tool activity, usage, and cancellation;
- Session create, resume, list, delete, title, undo, branch, and export;
- image and clipboard attachments;
- model selection and provider credential setup;
- Context, Memory, and runtime status;
- Confirm and Clarify round-trips;
- local TUI commands listed by `/help`.

The TUI does not expose Gateway administration, Sandbox controls, Evolver,
remote Skill installation, dynamic command discovery, voice controls, or
compatibility RPC fallbacks.

## Development

```bash
cd ui-tui
npm ci
npm run gen:rpc
npm run lint:rpc
npm run lint:rpc-surface
npm run type-check
npm test
npm run build
```

From the repository root:

```bash
uv run pico --check
uv run pico
uv run pico --dev
```

`rpc-schema/openrpc.json` is the protocol source consumed by
`scripts/gen-rpc-types.mjs`. `scripts/check-rpc-surface.mjs` rejects production
frontend calls to methods outside that schema. Python registration parity is
checked by `tests/test_rpc_schema_match.py`.

## Attribution

The TUI retains MIT-licensed portions of hermes-agent. See `../NOTICES.md` and
`../LICENSES/MIT-hermes-agent.txt`.
