# TUI

The terminal frontend in `ui-tui/` renders chat and overlays. It talks to the
Runtime only through TUI-RPC and never imports Python Runtime internals.

## Language

**Overlay**:
A modal layer over the chat view, tracked in `overlayStore`. Supported kinds are
Confirm, Clarify, Agents, Model Picker, Session Picker, and Pager.

**Message Line**:
One rendered transcript row.
_Avoid_: "chat stream" for the UI element; Chat Stream is the event feed.

**Status Bar**:
The status rule rendered above or below the composer, or hidden.

**Agents Overlay**:
The overlay showing the current subagent tree and token or cost aggregates.

**Confirm Overlay**:
The countdown overlay for a destructive Confirm Round-Trip. Its answer resolves
the paused Runtime request through `confirm.respond`.

**Clarify Overlay**:
The prompt used by `ask_user`. Its answer returns through `clarify.respond`.

**Current Session**:
The Session currently bound to the TUI. Switching Session rebinds the Chat
Stream and visible transcript to another Runtime Session key.

**Session Switch Flight**:
The serialized close-and-rebind operation that changes the Current Session.
While it is active, submissions remain queued. Its epoch prevents an older
create or resume response from overwriting a newer switch, and the old Session
must close successfully before the new binding can commit.

**Session Mutation Flight**:
A serialized operation that changes Session state outside a normal Turn, such
as undo, retry, branch, or delete. It is mutually exclusive with Session Switch
Flight and image attachment, and submissions remain queued until it settles.

**Chat Stream**:
The `turn.subscribe` event feed carrying token, reasoning, Tool, completion,
error, and usage events for the Current Session.

**Subagent Delivery**:
The `subagent.delivered` server-originated Chat Stream event carrying the final
text of a `SUBAGENT`-origin Turn. It appends an assistant Message Line without
starting or settling the Current Session's bound user submission.

**Submission ID**:
A client-generated identifier for one `turn.send` attempt. Turn-scoped start,
completion, and error events echo it so a late event can settle its own Turn
without mutating a newer submission. The Runtime binds it to the submitted
request, not only the Session lane, so a preceding system-origin turn cannot
emit turn-scoped streaming or lifecycle events, settle, or clear the queued
user turn. `message.start` is emitted only when that exact request begins
running. `turn.send` rejects with `turn_in_progress` while the Session's
Scheduler Lane already owns work, so an accepted request cannot wait behind a
system turn past the client ack watchdog.

**Slash Command System**:
The fixed local registry in `app/slash/`. It contains the supported
conversational commands and has no dynamic catalog or backend dispatch
fallback.

**TUI-RPC Client**:
The single socket client in `tuiRpcClient.ts`. It performs `system.hello`,
routes notifications, and shares one connection with Chat Stream
subscriptions.
