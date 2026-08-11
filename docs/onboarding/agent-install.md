# Pico installation contract for agents

Use this document when an automation agent is asked to install Pico for a user. Do not infer release URLs, expose secrets, publish artifacts, or initialize a repository the user did not select.

## Required inputs

- Target operating system: macOS/Linux or Windows.
- Absolute path of the target Git repository.
- A trusted Pico wheel URL, unless the user explicitly accepts a source-checkout preview.
- A trusted, compatible Myna wheel URL when Memory is required.
- Provider choice and credentials supplied directly by the user.
- Whether a real billed first Turn is allowed. Default to no if the user did not authorize one.

If either wheel URL is missing, report that boundary. Do not replace it with an unpinned package, a local developer checkout, or a guessed release.

## Installation

macOS/Linux:

```bash
export PICO_WHEEL_URL="<trusted-pico-wheel-url>"
export MYNA_WHEEL_URL="<trusted-myna-wheel-url>"
curl -fsSL https://raw.githubusercontent.com/Hackerismydream/pico/main/install.sh | sh
```

Windows PowerShell:

```powershell
$env:PICO_WHEEL_URL = "<trusted-pico-wheel-url>"
$env:MYNA_WHEEL_URL = "<trusted-myna-wheel-url>"
irm https://raw.githubusercontent.com/Hackerismydream/pico/main/install.ps1 | iex
```

Do not print secret values in logs. Wheel URLs may themselves be credentialed; redact query strings and signed parameters in reports.

## User-owned configuration boundary

Change into the exact repository before onboarding:

```bash
cd <absolute-target-repository>
pico onboard --skip-test
```

The interactive wizard is the preferred secret-entry path. It shows the Myna setup preview and requires consent before writes. The agent should pause while the user enters credentials.

Only use `--non-interactive --api-key ...` when the user explicitly authorizes non-interactive secret handling. Shell arguments can be visible to local process inspection and history tooling.

## Verification

Run all read-only checks from the target repository:

```bash
uv tool list
pico plugins
pico channels list
pico doctor --json
myna doctor --format json
```

Acceptance:

- `uv tool list` shows `pico-harness` and exposes both the `pico` and `myna` executables when the wheels were paired.
- `pico plugins` identifies the installed Myna plugin.
- `pico doctor --json` is valid JSON and its `memory.state` is not `error`.
- `myna doctor --format json` is valid JSON and belongs to the selected repository.
- No credential value appears in captured output.

If the user authorizes a billed live check, run:

```bash
pico doctor --probe
myna doctor --live --strict
```

Do not call a configured Provider "verified" unless its live check passed. Do not call Feishu connected until a human sends an inbound message and receives the Pico reply.

## Feishu handoff

The user must own App ID/App Secret access, permission approval, application publication, and the inbound test message. Follow [feishu.zh-CN.md](feishu.zh-CN.md), then verify only redacted local state:

```bash
pico channels get feishu
pico gateway --workspace <absolute-target-repository> --verbose
```

Never paste Feishu secrets into an issue, pull request, chat transcript, screenshot, or committed file.
