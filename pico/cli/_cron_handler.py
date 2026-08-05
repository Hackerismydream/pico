"""Shared ``on_cron_job`` factory used by both ``gateway`` and ``agent``.

Extracted from commands.gateway() so both entry points run cron jobs with
identical semantics: a scheduled reminder fires as a CRON-origin spine turn
bound to the ``cron:<job_id>`` session, and the reply is delivered by the hub
(single target) or broadcast to the resolved targets.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

if TYPE_CHECKING:
    from pico.channels.manager import ChannelManager
    from pico.proactive_engine.schedulers.cron.types import CronJob
    from pico.session.manager import SessionManager
    from pico.spine import TurnHandle, TurnRequest
    from pico.spine.delivery import DeliveryHub


def _ms_to_local_str(ms: int | None) -> str | None:
    """Render a ms-since-epoch timestamp as local HH:MM for user-facing text."""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%H:%M")
    except (OSError, ValueError):
        return None


def _format_schedule_origin(job: "CronJob") -> str:
    """Describe when the reminder was originally set, for the user.

    - 'at' jobs: "set at <HH:MM>, scheduled for <HH:MM>" (at_ms is the fire time)
    - 'every' jobs: "set at <HH:MM>, recurring every <N>s"
    - 'cron' jobs: "set at <HH:MM>, cron <expr>"
    """
    created = _ms_to_local_str(job.created_at_ms) or "?"
    kind = job.schedule.kind
    if kind == "at":
        fire_at = _ms_to_local_str(job.schedule.at_ms) or "?"
        return f"set at {created}, scheduled for {fire_at}"
    if kind == "every":
        secs = (job.schedule.every_ms or 0) // 1000
        return f"set at {created}, recurring every {secs}s"
    if kind == "cron" and job.schedule.expr:
        return f"set at {created}, cron `{job.schedule.expr}`"
    return f"set at {created}"


def make_on_cron_job(
    hub: "DeliveryHub",
    *,
    submit: "Callable[[TurnRequest], TurnHandle]",
    readback_texts: "dict[str, str] | None" = None,
    channel_manager: "ChannelManager | None" = None,
    session_manager: "SessionManager | None" = None,
    default_channel: str = "cli",
) -> Callable[["CronJob"], Awaitable[str | None]]:
    """Build the CronService.on_job callback. Every cron turn runs through the
    spine ``submit`` as a CRON-origin turn.

    ``submit`` (required) is the spine entry (build_gateway / build_repl /
    build_tui scheduler). A single-target delivering job (deliver=True, the
    user-facing reminder the cron tool creates) rides the hub to its one outlet.
    A broadcast (more than one resolved target) or a silent job (deliver=False)
    submits with the job's own (ephemeral) channel as the source so the hub drops
    the reply; a broadcast is then delivered explicitly to every target, a silent
    job delivers nothing.

    ``readback_texts`` is the host's per-conversation reply-text map. A CRON
    turn submits, then this reads its reply from
    ``readback_texts[cron:<job_id>]`` and pops it. The gateway needs the reply
    for multi-target delivery and the TUI needs it for ``cron.delivered``.

    ``default_channel`` is used when the job payload doesn't specify one —
    REPL passes "cli" so the reminder renders inline in the terminal; the
    gateway lets the payload's own channel decide.

    ``channel_manager`` / ``session_manager`` drive delivery resolution
    (``resolve_cron_delivery``). Without ``channel_manager`` the enabled
    set is empty — meaning every channel is considered ephemeral, and
    delivery falls back to forward_channels broadcast. REPL paths that
    have no real channels (agent-only mode) pass ``None`` for both and
    accept that ephemeral reminders are dropped with a warning.

    Outcomes and failures flow only through the Spine handle and CronService
    state. The callback has no additional scheduling side effects.
    """

    async def on_cron_job(job: "CronJob") -> str | None:
        from pico.config.loader import load_config
        from pico.proactive_engine.schedulers.cron.tool import (
            is_ephemeral_channel,
            resolve_cron_delivery,
        )
        from pico.spine import ChatType, Origin, Source, Text, TurnRequest

        # Include the originally-scheduled time so the reminder text can
        # echo "set at 17:05" back to the user — otherwise the agent only
        # knows "right now".
        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' ({_format_schedule_origin(job)}) "
            "has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}\n\n"
            "When you reply, mention when the reminder was originally set "
            '(e.g. "你在 17:05 提醒的 ...") so the user remembers the '
            "context."
        )

        # Resolve delivery targets at TRIGGER time (reading cron config now lets
        # ``cron config set`` take effect on the next fire) — response-independent,
        # so it can run before the turn; len(targets) decides the path.
        cron_cfg = load_config().cron
        enabled_channels = set(channel_manager.enabled_channels) if channel_manager is not None else set()
        targets, warnings = resolve_cron_delivery(
            channel=job.payload.channel or default_channel,
            chat_id=job.payload.to or "direct",
            forward_channels=cron_cfg.forward_channels,
            enabled_channels=enabled_channels,
            session_manager=session_manager,
        )
        for w in warnings:
            logger.warning("Cron job '{}' ({}): {}", job.name, job.id, w)

        # Every cron turn runs through the spine. Delivery is explicit per branch:
        # a single-target delivering job rides the hub to its one outlet; every
        # other case (no forward, a broadcast, or a silent job) submits with the
        # job's own channel as the source — ephemeral for the realistic cases, so
        # it has no gateway outlet and the hub drops the reply. A broadcast then
        # delivers explicitly below; a silent job delivers nothing. run_turn sets
        # the cron-context guard itself (in the lane task), keyed on origin=CRON.
        deliver_via_hub = job.payload.deliver and len(targets) == 1
        if deliver_via_hub:
            src_channel, src_chat = targets[0].channel, targets[0].chat_id
        else:
            src_channel = job.payload.channel or default_channel
            src_chat = job.payload.to or "direct"
            # A silent job (deliver=False) stays silent because its ephemeral
            # source has no gateway outlet (the hub drops the reply). A silent job
            # on a non-ephemeral channel — only reachable by hand-editing jobs.json,
            # since every creation path sets deliver=True — WOULD be delivered by
            # the hub; warn so this edge is visible rather than a silent change.
            if not job.payload.deliver and not is_ephemeral_channel(src_channel, enabled_channels):
                logger.warning(
                    "Cron job '{}' ({}): silent job on non-ephemeral channel '{}' "
                    "is delivered under the spine (no outlet-less suppression for "
                    "real channels)",
                    job.name,
                    job.id,
                    src_channel,
                )
        req = TurnRequest(
            origin=Origin.CRON,
            source=Source(channel=src_channel, chat_id=src_chat, sender_id="cron", chat_type=ChatType.DM),
            text=reminder_note,
            conversation=f"cron:{job.id}",
        )
        await submit(req).result()
        # Read the reply back for host-specific delivery and pop it so the
        # long-running map does not accumulate.
        response: str | None = readback_texts.pop(f"cron:{job.id}", None) if readback_texts is not None else None

        # Broadcast a multi-target delivering job to every resolved target: the hub
        # dropped the reply (no outlet for the ephemeral source), so this is the
        # only delivery. It does NOT skip on a message-tool self-send — a self-send
        # to an ephemeral source never reaches the user under the daemon, so
        # broadcasting the reply to all targets is both simpler and strictly better
        # than the legacy self-send guard, which suppressed the broadcast and left
        # the other targets with nothing.
        if job.payload.deliver and len(targets) > 1 and response:
            for t in targets:
                await hub.post(
                    Text(
                        content=response,
                        source=Source(
                            channel=t.channel,
                            chat_id=t.chat_id,
                            sender_id="cron",
                            chat_type=ChatType.DM,
                        ),
                    )
                )
        return response

    return on_cron_job


__all__ = ["make_on_cron_job"]
