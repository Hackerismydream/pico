"""Delivery: what a channel can do (Capabilities), the streaming opt-in
(SupportsStreaming), the per-channel send surface (Outlet), and the hub that
routes each deliverable to its outlet (DeliveryHub).

The hub keeps one bounded queue and one serial worker per outlet: a deliverable
is routed by its source channel into that outlet's queue, and the queue is the
backpressure point — a full queue blocks only that channel's sender, never the
others (no cross-outlet head-of-line blocking), while same-channel order is held
by the single worker. This mirrors the lane model on the delivery side.

spine never imports channels; channels import the vocabulary here (via the
channels.contract re-export), not the reverse.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loguru import logger

from pico.spine._barrier import finish_barrier
from pico.spine.events import (
    Deliverable,
    MediaOut,
    Notice,
    NoticeKind,
    StreamDelta,
    Text,
    TurnEnded,
    TurnEvent,
    TurnFailed,
    TurnStarted,
)
from pico.tracing import semconv, trace

DeliveryFailureSink = Callable[[Notice], Awaitable[None]]


class TerminalDeliveryError(RuntimeError):
    """A platform rejected delivery in a way that retrying cannot repair."""


@dataclass(frozen=True)
class Capabilities:
    """What a channel can do, declared explicitly (not inferred from methods).

    Only capabilities with a real consumer live here. ``media``/``reactions``
    are adapter-internal today (nothing routes on them) — add them back with
    their consumer when one exists.
    """

    interactive_login: bool = False  # QR / scan login; read by CLI `channel login`
    streaming: bool = False  # SupportsStreaming slot; activated in B


@runtime_checkable
class SupportsStreaming(Protocol):
    """Opt-in incremental delivery (edit-in-place). Inert until the agent loop
    is wired to produce stream chunks (scope B)."""

    async def send_stream_chunk(self, chat_id: str, stream_id: str, delta: str, *, done: bool = False) -> None: ...


@runtime_checkable
class Outlet(Protocol):
    """A channel's send surface. ``deliver`` either renders the deliverable or, if
    the channel can't express it, eats it with a normal return (logging its own
    skip). A real failure raises: ``TerminalDeliveryError`` drops immediately,
    while other exceptions are retried. Eating is not failure. Lifecycle
    (connect/teardown) stays on the channel; an outlet is just the send seam."""

    name: str
    capabilities: Capabilities

    async def deliver(self, out: Deliverable) -> None: ...


_SEND_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubles each retry (1, 2, 4)
_OUTLET_QUEUE_MAXSIZE = 100  # per-outlet backpressure bound; config knob lands with its consumer


def _is_terminal_deliverable(out: Deliverable) -> bool:
    """Only a turn's terminal output gets a delivery span. Progress surface
    (stream deltas, reasoning, notices, tool events) would bury the turn."""
    return isinstance(out, (Text, MediaOut))


@dataclass(frozen=True)
class _StreamClose:
    """A marker the hub puts on an outlet's queue so the stream's done=True chunk
    is sent after the last StreamDelta still in flight (a sourceless lifecycle
    event can't ride the queue itself, but this can)."""

    conversation_id: str


@dataclass(frozen=True)
class _Routed:
    """A queued deliverable plus the trace ids captured at enqueue.

    The outlet worker is resident (one task per channel, many turns), so its
    contextvars snapshot belongs to whichever turn started it. Carrying the ids
    on the item is what lets the worker's span join the right turn."""

    out: Deliverable
    trace_id: str | None
    parent_span_id: str | None


class DeliveryHub:
    """Routes each deliverable into its source channel's bounded queue, where a
    per-outlet serial worker delivers it (retrying transient failures with backoff).
    Holds the outlet registry plus a queue and worker per outlet; no turn state.

    Streaming rides the same queue: StreamDelta is sent via send_stream_chunk and
    close_stream enqueues a marker so the closing chunk follows the deltas. The
    open-stream table is the worker's alone (single owner); the channel a stream
    rides is recorded synchronously on enqueue so close_stream can route to it."""

    def __init__(
        self,
        send_max_retries: int = _SEND_MAX_RETRIES,
        *,
        on_delivery_failure: DeliveryFailureSink | None = None,
    ) -> None:
        self._send_max_retries = send_max_retries
        # Out-of-band, deliberately not routed through dispatch: the channel that
        # just exhausted its retries is the one that would have to carry the
        # report, so re-dispatching would loop through the broken outlet.
        self._on_delivery_failure = on_delivery_failure
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._outlets: dict[str, Outlet] = {}
        self._queues: dict[str, asyncio.Queue[_Routed | _StreamClose]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        # conversation_id -> channel, written on enqueue (sink path), read by
        # close_stream to route its marker; the open-stream table below is the
        # worker's (conversation_id -> chat_id, present iff the stream is open).
        self._stream_channel: dict[str, str] = {}
        self._open_streams: dict[str, str] = {}

    def register(self, outlet: Outlet) -> None:
        # Register-once, at startup: a running worker captures its outlet when it
        # starts, so re-registering a different outlet for a live channel does not
        # hot-swap it.
        if self._closed:
            raise RuntimeError("delivery hub is closed")
        if outlet.name in self._outlets:
            raise ValueError(f"outlet {outlet.name!r} is already registered")
        self._outlets[outlet.name] = outlet

    async def dispatch(self, out: Deliverable) -> None:
        await self._enqueue(out)

    async def post(self, out: Deliverable) -> None:
        """Send a deliverable that did not come from a turn.
        Routes like dispatch; the caller stamps source.channel. Returns once the
        event is queued, not once delivered — delivery is the outlet worker's, and
        a full queue backpressures this channel's caller."""
        await self._enqueue(out)

    async def close_stream(self, conversation_id: str) -> None:
        """End a conversation's stream. Routes a close marker through the outlet's
        queue so its done=True chunk follows the last StreamDelta still in flight.
        Driven by a lifecycle event (TurnEnded / TurnFailed); a conversation with
        no open stream is a no-op."""
        if self._closed:
            raise RuntimeError("delivery hub is closed")
        channel = self._stream_channel.pop(conversation_id, None)
        if channel is None:
            return
        queue = self._queues.get(channel)
        if queue is not None:
            try:
                await self._put(queue, _StreamClose(conversation_id))
            except BaseException:
                if not self._closed:
                    self._stream_channel.setdefault(conversation_id, channel)
                raise

    async def _put(self, queue: asyncio.Queue[_Routed | _StreamClose], item: _Routed | _StreamClose) -> None:
        """Commit one item unless close won while a full queue blocked it."""
        await queue.put(item)
        if self._closed:
            self.drain()
            raise RuntimeError("delivery hub is closed")

    async def _enqueue(self, out: Deliverable) -> None:
        if self._closed:
            raise RuntimeError("delivery hub is closed")
        if out.source is None:
            raise ValueError(f"cannot route a {type(out).__name__} with no source")
        channel = out.source.channel
        if channel not in self._outlets:
            logger.warning("no outlet for channel {!r}; dropping {}", channel, type(out).__name__)
            if _is_terminal_deliverable(out):
                self._deliver_span(out, channel, semconv.CHANNEL_NO_OUTLET, attempts=0)
            return
        if isinstance(out, StreamDelta):
            # Remember the channel this stream rides so a later close_stream (driven
            # by a sourceless lifecycle event) can route its marker here.
            self._stream_channel.setdefault(out.conversation_id, channel)
        queue = self._queues.get(channel)
        if queue is None:
            queue = asyncio.Queue(maxsize=_OUTLET_QUEUE_MAXSIZE)
            self._queues[channel] = queue
        worker = self._workers.get(channel)
        if worker is None or worker.done():
            # Restart on done() too, not just absence: the worker is resident
            # (blocks on get), so a dead one would leave its queue unconsumed and
            # silently deadlock this channel's senders. Mirrors the lane worker.
            self._workers[channel] = asyncio.create_task(self._run_outlet(channel))
        ctx = trace.current()
        routed = _Routed(
            out=out,
            trace_id=getattr(ctx, "trace_id", None),
            parent_span_id=getattr(ctx, "parent_span_id", None),
        )
        await self._put(queue, routed)  # full queue blocks only this channel (per-outlet backpressure)

    async def _run_outlet(self, channel: str) -> None:
        queue = self._queues[channel]
        outlet = self._outlets[channel]
        while not self._closed:
            item = await queue.get()
            try:
                if isinstance(item, _StreamClose):
                    await self._close_stream_chunk(outlet, item.conversation_id)
                elif isinstance(item.out, StreamDelta):
                    await self._stream_chunk(outlet, item.out)
                else:
                    await self._deliver_routed(outlet, item)
            except Exception:
                # A rendering bug must not kill the resident worker: its queue
                # would then sit unconsumed until the next enqueue restarts it,
                # silently stalling this channel in between.
                logger.exception("outlet worker recovered from a delivery error: channel={!r}", channel)
            finally:
                # Always mark done — including the eat / retries-exhausted path —
                # so wait_idle's join() reflects every dequeued item, never hangs.
                queue.task_done()

    async def _stream_chunk(self, outlet: Outlet, ev: StreamDelta) -> None:
        # A non-streaming outlet eats the delta (the full text reaches it another
        # way); only an outlet that both can and declares streaming gets chunks.
        if not (isinstance(outlet, SupportsStreaming) and outlet.capabilities.streaming):
            return
        chat_id = ev.source.chat_id
        self._open_streams.setdefault(ev.conversation_id, chat_id)  # first delta opens the stream
        await outlet.send_stream_chunk(chat_id, ev.conversation_id, ev.delta, done=False)

    async def _close_stream_chunk(self, outlet: Outlet, conversation_id: str) -> None:
        chat_id = self._open_streams.pop(conversation_id, None)
        if chat_id is None:
            return  # no open stream (empty turn, or a non-streaming outlet) -> no-op
        if isinstance(outlet, SupportsStreaming) and outlet.capabilities.streaming:
            await outlet.send_stream_chunk(chat_id, conversation_id, "", done=True)

    def _deliver_span(
        self,
        out: Deliverable,
        channel: str,
        outcome: str,
        *,
        attempts: int,
        error: str | None = None,
    ) -> None:
        chat_id = getattr(out.source, "chat_id", None) if out.source is not None else None
        conversation_id = out.conversation_id or (f"{channel}:{chat_id}" if chat_id else None)
        with trace.span(
            "channel.deliver",
            semconv.channel_deliver(
                channel=channel,
                event=type(out).__name__,
                conversation_id=conversation_id,
                outcome=outcome,
                attempts=attempts,
                error=error,
            ),
            kind="channel",
            session_key=conversation_id,
            channel=channel,
            chat_id=chat_id,
        ) as span:
            if outcome != semconv.CHANNEL_DELIVERED:
                span.error(outcome)

    async def _deliver_routed(self, outlet: Outlet, item: _Routed) -> None:
        outcome, attempts, error = await self._deliver_with_retry(outlet, item.out)
        if not _is_terminal_deliverable(item.out):
            return
        with trace.attach(item.trace_id, item.parent_span_id):
            self._deliver_span(item.out, outlet.name, outcome, attempts=attempts, error=error)
        if outcome == semconv.CHANNEL_DROPPED:
            await self._report_delivery_failure(item.out, outlet.name, error)

    async def _report_delivery_failure(self, out: Deliverable, channel: str, error: str | None) -> None:
        if self._on_delivery_failure is None:
            return
        notice = Notice(
            kind=NoticeKind.DELIVERY_FAILED,
            source=out.source,
            detail=f"{channel}:{type(out).__name__}:{error or 'unknown'}",
            conversation_id=out.conversation_id,
        )
        try:
            await self._on_delivery_failure(notice)
        except Exception:
            logger.exception("delivery-failure sink raised: channel={!r}", channel)

    async def _deliver_with_retry(self, outlet: Outlet, out: Deliverable) -> tuple[str, int, str | None]:
        """Deliver with backoff unless the outlet reports a terminal failure."""
        delay = _RETRY_BASE_DELAY
        for attempt in range(self._send_max_retries + 1):
            try:
                await outlet.deliver(out)
                return semconv.CHANNEL_DELIVERED, attempt + 1, None
            except TerminalDeliveryError as exc:
                logger.error(
                    "terminal delivery failure: channel={!r} event={} reason={}",
                    outlet.name,
                    type(out).__name__,
                    exc,
                )
                return semconv.CHANNEL_DROPPED, attempt + 1, type(exc).__name__
            except Exception as exc:
                if attempt == self._send_max_retries:
                    logger.error(
                        "delivery failed after {} retries: channel={!r} event={} reason={}",
                        self._send_max_retries,
                        outlet.name,
                        type(out).__name__,
                        exc,
                    )
                    return semconv.CHANNEL_DROPPED, attempt + 1, type(exc).__name__
                await asyncio.sleep(delay)
                delay *= 2

    def drain(self) -> int:
        """Drop every not-yet-delivered (still-queued) event and return the count.
        Synchronous (no await) so it is atomic against the live workers. This only
        drops queued events; a best-effort flush within a shutdown window is not yet
        implemented."""
        dropped = 0
        for queue in self._queues.values():
            while not queue.empty():
                queue.get_nowait()
                queue.task_done()  # keep unfinished count consistent so join() can't hang
                dropped += 1
        if dropped:
            logger.warning("delivery hub drained {} undelivered events on shutdown", dropped)
        return dropped

    async def wait_idle(self, channel: str) -> None:
        """Block until this channel's outlet has delivered everything queued — the
        render barrier a caller awaits after a turn's result() before it treats the
        output as on-screen (result() means 'no more events', not 'delivered'). A
        channel with nothing ever queued is already idle."""
        queue = self._queues.get(channel)
        if queue is None:
            return
        await queue.join()

    async def _finish_close(self) -> None:
        workers = tuple(self._workers.values())
        for worker in workers:
            worker.cancel()
        try:
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            self._workers.clear()
            self.drain()
            self._stream_channel.clear()
            self._open_streams.clear()

    async def aclose(self) -> None:
        """Seal the hub and finish the shared barrier before propagating cancellation."""
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._finish_close())
        await finish_barrier(self._close_task)


def make_hub_sink(hub: DeliveryHub) -> Callable[[TurnEvent], Awaitable[None]]:
    """Adapt the hub into a scheduler EventSink: deliverables route through the
    hub; lifecycle events carry no source, so they are dropped here and never
    reach the deliverable-only enqueue path (lifecycle -> taps lands later). The
    REPL and the gateway share this sink; the TUI keeps its own (it fires
    message.complete / error after the render barrier)."""

    async def sink(event: TurnEvent) -> None:
        if isinstance(event, (TurnStarted, TurnFailed, TurnEnded)):
            return
        await hub.dispatch(event)

    return sink
