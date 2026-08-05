# Pico TUI black-box test harness

> Status: current checkout-only test utility.

This package drives terminal subprocesses through the external `tui-use` CLI.
It is separate from the React/Ink unit tests and Python TUI-RPC contract tests.

## Requirements

- Node.js 22;
- `tui-use` available on `PATH`;
- Pico development dependencies through `uv`;
- a built TUI or source-mode command for tests that launch the full UI.

Install the external backend once:

```bash
npm install -g tui-use
uv sync
```

## Test layers

```bash
# Harness unit tests only
uv run pytest tests/tui/autotest/tests/ -m "not e2e" -q

# All black-box tests, including real subprocesses
uv run pytest tests/tui/autotest/tests/ -m e2e -q -rs

# Ad-hoc command smoke
uv run python -m tests.tui.autotest smoke \
  "uv run pico --check"
```

The repository's default pytest configuration excludes `e2e`. A required
black-box Gate must request it explicitly and treat skip/infrastructure failure
according to that Gate.

## Python API

```python
from tests.tui.autotest.runner import Harness

h = Harness(cols=120, rows=40)
try:
    h.env_set({"FORCE_COLOR": "1"})
    h.spawn("uv run pico")
    assert h.wait("Pico", timeout=25.0)
    h.type("/status")
    h.press("enter")
    assert h.wait(r"Model:|Provider:", timeout=10.0)
    h.press("escape")
    h.press("ctrl+c")
    assert h.expect_exit(0, timeout=10.0)
finally:
    h.kill()
```

The pytest `harness` fixture creates a fresh instance and always calls
`kill()` during teardown:

```python
def test_status(harness):
    harness.spawn("uv run pico")
    assert harness.wait("Pico", timeout=25.0)
```

Key methods:

| Method | Purpose |
| --- | --- |
| `spawn(command)` | launch one terminal subprocess |
| `env_set(mapping)` | add subprocess environment overrides |
| `wait(pattern, timeout)` | poll rendered alt-screen content |
| `type(text)` | type literal text |
| `press(key)` | send a key such as `enter`, `escape`, or `ctrl+c` |
| `dump()` | return rendered screen rows |
| `expect_exit(code, timeout)` | wait for exact exit status |
| `kill()` | idempotent cleanup |

## Readiness and rendering

`tui-use snapshot` observes the rendered alternate screen. Text printed before
the app enters the alternate screen may be absent.

Prefer stable visible patterns:

- `Pico`;
- a visible model name;
- `Model:` or `Provider:`;
- text in the current overlay.

Avoid:

- startup bytes only visible in scrollback;
- an exact default Session id;
- provider names that depend on the operator's Config;
- color/emoji bytes as the only readiness signal.

## Exit behavior

Pico TUI exit depends on current UI state:

- inline state: one `Ctrl-C` may exit;
- overlay open: `Escape` dismisses, then `Ctrl-C` exits;
- composer has text: first `Ctrl-C` may clear/cancel, second exits;
- active Turn: cancellation and process exit are separate events.

Robust cleanup:

```python
from tests.tui.autotest.runner import BackendError

for key in ("escape", "ctrl+c", "ctrl+c"):
    try:
        harness.press(key)
    except BackendError:
        break
```

Always retain `kill()` in a `finally` block or use the fixture.

## Command quoting

`tui-use start` invokes a shell. Complex nested quoting and shell-special
characters may be retokenized before the target sees them.

Prefer:

- launching the TUI with a simple command;
- typing retained slash commands after startup;
- setting complex values through `env_set`;
- direct Python/TUI-RPC tests for argument-parser contracts.

Do not use the black-box harness when a deterministic method-level test proves
the same contract more directly.

## Live Provider tests

`test_e2e_pico_tui_chat.py` exercises the live chat path. It may incur cost and
depends on an accessible configured model. A skip indicates missing optional
environment in an ad-hoc run; it is not live success.

The other checked-in E2E files cover cheap subprocess startup, Ctrl-C,
streaming/log-overlay behavior, TUI `--check`, and `/status`.

Never embed keys in test code or transcripts. Isolate state with `PICO_HOME`
and a temporary Workspace when the test mutates configuration or Sessions.

## Isolated state

```python
def test_with_isolated_state(harness, tmp_path):
    harness.env_set(
        {
            "PICO_HOME": str(tmp_path / "pico-home"),
            "FORCE_COLOR": "1",
        }
    )
    harness.spawn("uv run pico --check")
```

Use `PICO_HOME` instead of depending on a global `HOME` override. If a test
intentionally changes `HOME`, document why the broader process environment is
part of the scenario.

## Ad-hoc smoke exit codes

| Code | Meaning |
| ---: | --- |
| 0 | spawn, readiness, and target exit succeeded |
| 1 | readiness timeout or target exited with another code |
| 2 | harness/backend error or invalid CLI usage |

## Current limits

- depends on the external `tui-use` backend;
- no Windows contract;
- no record/replay DSL or golden terminal snapshots;
- only one subprocess per `Harness`;
- shell quoting is not lossless;
- real chat tests are opt-in and non-deterministic;
- this harness does not replace TUI unit, RPC schema, type, or build checks.

Implementation authority is `runner.py`, `cli.py`, and the checked-in tests in
`tests/tui/autotest/tests/`. Historical proposal and local `RepoMem` paths are
not required to use or maintain this harness.
