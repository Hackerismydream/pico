"""Run lifecycle effects that sit outside the runtime loop."""

from __future__ import annotations

import time

from .run_events import RunEvent
from .tool_runner import ToolExecutionResult
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
        forced_metadata=None,
        source="",
        checkpoint_trigger="tool_executed",
    ):
        tool_started_at = time.monotonic()
        started_payload = {"name": name, "args": args}
        if source:
            started_payload["source"] = source
        host.emit_runtime_event("tool_started", started_payload)

        execution = (
            _forced_execution(forced_result, forced_metadata)
            if forced_result is not None
            else host.execute_tool(name, args)
        )
        result = execution.content
        metadata = dict(execution.metadata or {})
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
            host.apply_run_events(
                task_state,
                [
                    RunEvent(
                        "runtime_reminder_emitted",
                        {"reason": "tool_rejection_recovery", "message": rejection_recovery, "tool": name, "args": args},
                    )
                ],
            )
            host.emit_trace(
                task_state,
                "runtime_reminder_emitted",
                {"reason": "tool_rejection_recovery", "message": rejection_recovery, "tool": name, "args": args},
            )
            host.record({"role": "assistant", "content": rejection_recovery, "created_at": now()})

        affected_paths = list(metadata.get("affected_paths", []) or [])
        events = [RunEvent("tool_executed", {"name": name, "metadata": metadata})]
        if affected_paths:
            events.append(RunEvent("changed_paths_recorded", {"paths": affected_paths}))
        events.append(RunEvent("task_list_updated", {"tasks": host.task_ledger_snapshot()}))
        verification = metadata.get("verification")
        if verification:
            verification = dict(verification)
            if not verification.get("checked_paths"):
                verification["checked_paths"] = list(affected_paths)
            events.append(RunEvent("verification_recorded", {"verification": verification}))
        host.apply_run_events(task_state, events)
        artifact_state = host.artifact_state_for_run(task_state)
        artifact_graph = dict(artifact_state.get("artifact_graph", {}) or {})
        verification_plan = dict(artifact_state.get("verification_plan", {}) or {})
        update_events = []
        if artifact_graph:
            update_events.append(RunEvent("artifact_graph_updated", {"artifact_graph": artifact_graph}))
        if verification_plan:
            update_events.append(RunEvent("verification_plan_updated", {"verification_plan": verification_plan}))
        if update_events:
            host.apply_run_events(task_state, update_events)
        host.persist_run_state(task_state)
        host.emit_trace(task_state, "tool_executed", tool_payload)

        host.drain_subagent_notifications()

        checkpoint = host.create_checkpoint(task_state, user_message, trigger=checkpoint_trigger)
        host.apply_run_events(
            task_state,
            [RunEvent("checkpoint_created", {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": checkpoint_trigger})],
        )
        host.persist_run_state(task_state)
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
        host.persist_run_state(task_state)
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


def _forced_execution(content: str, metadata: dict | None = None) -> ToolExecutionResult:
    merged = {
        "tool_status": "rejected",
        "tool_error_code": "runtime_control_rejected",
        "security_event_type": "",
        "risk_level": "low",
        "read_only": True,
        "affected_paths": [],
        "workspace_changed": False,
        "diff_summary": [],
        "effective_effects": [],
    }
    merged.update(dict(metadata or {}))
    return ToolExecutionResult(
        content=str(content),
        metadata=merged,
        effects=set(),
    )
