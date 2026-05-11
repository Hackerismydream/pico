"""Run lifecycle effects that sit outside the runtime loop."""

from __future__ import annotations

import time

from .run_events import RunEvent
from .run_reducer import reduce_run_state
from .workspace import clip, now


class RunLifecycle:
    def execute_tool_step(
        self,
        host,
        task_state,
        run_context,
        user_message,
        name,
        args,
        *,
        forced_result=None,
        source="",
        checkpoint_trigger="tool_executed",
    ):
        reduce_run_state(task_state, RunEvent("tool_executed", {"name": name}))
        tool_started_at = time.monotonic()
        started_payload = {"name": name, "args": args}
        if source:
            started_payload["source"] = source
        host.emit_runtime_event("tool_started", started_payload)

        result = forced_result if forced_result is not None else host.run_tool(name, args)
        metadata = dict(host._last_tool_result_metadata or {})
        duration_ms = int((time.monotonic() - tool_started_at) * 1000)
        tool_payload = {
            "name": name,
            "args": args,
            "result": clip(result, 500),
            "duration_ms": duration_ms,
            **metadata,
        }
        if source:
            tool_payload["source"] = source
        host.emit_runtime_event("tool_finished", tool_payload)
        host.record({"role": "tool", "name": name, "args": args, "content": result, "created_at": now()})

        rejection_recovery = metadata.get("recovery_message", "")
        if rejection_recovery:
            host.emit_trace(
                task_state,
                "runtime_reminder_emitted",
                {"reason": "tool_rejection_recovery", "message": rejection_recovery, "tool": name, "args": args},
            )
            host.record({"role": "assistant", "content": rejection_recovery, "created_at": now()})

        affected_paths = list(metadata.get("affected_paths", []) or [])
        if affected_paths:
            host.remember_changed_paths(task_state, affected_paths)
            host.set_stage(task_state, "implementing")
        host.run_store.write_task_state(task_state)
        host.emit_trace(task_state, "tool_executed", tool_payload)

        verification = metadata.get("verification")
        if verification:
            host.record_verification_artifact(task_state, verification)
        host.drain_subagent_notifications()

        task_state.tasks = host.current_tasks()
        checkpoint = host.create_checkpoint(task_state, user_message, trigger=checkpoint_trigger)
        host.run_store.write_task_state(task_state)
        host.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": checkpoint_trigger,
            },
        )
        return result

    def finish_run(
        self,
        host,
        task_state,
        user_message,
        final,
        run_started_at,
        *,
        checkpoint_trigger=None,
        promote_memory=False,
        assess_completion=False,
    ):
        if assess_completion:
            host.assess_completion(task_state, user_message)
        host.record({"role": "assistant", "content": final, "created_at": now()})
        if promote_memory:
            host.promote_durable_memory(user_message, final)
        checkpoint = None
        if checkpoint_trigger:
            checkpoint = host.create_checkpoint(task_state, user_message, trigger=checkpoint_trigger)
        host.run_store.write_task_state(task_state)
        if checkpoint:
            host.emit_trace(
                task_state,
                "checkpoint_created",
                {
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "trigger": checkpoint_trigger,
                },
            )
        host.emit_trace(
            task_state,
            "run_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "final_answer": final,
                "run_duration_ms": int((time.monotonic() - run_started_at) * 1000),
            },
        )
        host.run_store.write_report(task_state, host.redact_artifact(host.build_report(task_state)))
        return final
