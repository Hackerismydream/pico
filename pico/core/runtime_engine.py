"""Runtime loop orchestration for Pico."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .run_events import RunEvent
from .run_reducer import reduce_run_state
from .workspace import now

CHECKPOINT_PARTIAL_STALE_STATUS = "partial-stale"
CHECKPOINT_WORKSPACE_MISMATCH_STATUS = "workspace-mismatch"


@dataclass
class CompletionTurnResult:
    text: str
    metadata: dict = field(default_factory=dict)
    truncated: bool = False
    recoverable_error: bool = False


@dataclass
class RunRequest:
    user_message: str
    raw_user_message: str = ""
    run_started_at: float = 0.0
    cancel_event: Any = None


@dataclass
class RunResult:
    final_answer: str


class RuntimeHost(Protocol):
    def build_prompt_for_turn(self, user_message: str) -> tuple[str, dict]: ...

    def auto_compact_history(self, prompt_metadata: dict) -> dict: ...

    def complete_model_turn(
        self,
        prompt: str,
        max_new_tokens: int,
        *,
        prompt_cache_key: str | None = None,
        prompt_cache_retention: str | None = None,
    ) -> CompletionTurnResult: ...

    def parse_with_metadata(self, raw: str): ...

    def execute_tool_request(
        self,
        task_state,
        run_context,
        user_message: str,
        name: str,
        args: dict,
        *,
        forced_result: str | None = None,
        source: str = "model",
        checkpoint_trigger: str = "tool_executed",
    ) -> None: ...

    def finish_run(
        self,
        task_state,
        user_message: str,
        final: str,
        run_started_at: float,
        *,
        checkpoint_trigger: str | None = None,
        promote_memory: bool = False,
        assess_completion: bool = False,
    ) -> str: ...

    def emit_trace(self, task_state, event: str, payload: dict | None = None) -> None: ...

    def record(self, item: dict) -> None: ...

    def write_task_state(self, task_state) -> None: ...

    def drain_subagent_notifications(self) -> None: ...

    def create_checkpoint(self, task_state, user_message: str, trigger: str) -> dict: ...

    def is_recoverable_model_error(self, exc: Exception) -> bool: ...

    def is_truncated_completion(self, metadata: dict) -> bool: ...

    def record_control_decision(self, task_state, phase: str, decision) -> None: ...

    def supports_prompt_cache(self) -> bool: ...

    def set_prompt_metadata(self, metadata: dict) -> None: ...

    def model_error_metadata(self, exc: Exception) -> dict: ...

    def before_tool(self, task_state, name: str, args: dict, user_message: str): ...

    def before_final(self, task_state, final: str, user_message: str): ...

    def runtime_reminder_once(self, reason: str) -> bool: ...


class RuntimeEngine:
    def run(self, host: RuntimeHost, task_state, run_context, request: RunRequest) -> RunResult:
        user_message = request.user_message
        raw_user_message = request.raw_user_message or user_message
        run_started_at = request.run_started_at or time.monotonic()

        while run_context.can_continue():
            if _cancelled(request.cancel_event):
                final = "Stopped because the current turn was cancelled."
                task_state.stop_retry_limit(final)
                return RunResult(host.finish_run(task_state, user_message, final, run_started_at))

            host.drain_subagent_notifications()
            reduce_run_state(task_state, RunEvent("model_attempted"))
            host.write_task_state(task_state)
            prompt, prompt_metadata = self._build_prompt(host, task_state, user_message)
            if not run_context.user_recorded:
                host.record({"role": "user", "content": raw_user_message, "created_at": now()})
                run_context.user_recorded = True
            self._checkpoint_prompt_state(host, task_state, user_message, prompt_metadata)
            host.emit_trace(
                task_state,
                "model_requested",
                {
                    "attempts": task_state.attempts,
                    "tool_steps": task_state.tool_steps,
                    "prompt_cache_key": prompt_metadata.get("prompt_cache_key"),
                },
            )

            model_started_at = time.monotonic()
            try:
                cache_supported = host.supports_prompt_cache()
                completion = host.complete_model_turn(
                    prompt,
                    run_context.current_max_new_tokens,
                    prompt_cache_key=prompt_metadata.get("prompt_cache_key") if cache_supported else None,
                    prompt_cache_retention="in_memory" if cache_supported else None,
                )
            except Exception as exc:
                recovered = self._handle_model_error(
                    host,
                    task_state,
                    run_context,
                    user_message,
                    prompt_metadata,
                    exc,
                    model_started_at,
                )
                if recovered:
                    continue
                final = f"Stopped after model error: {exc}"
                return RunResult(host.finish_run(task_state, user_message, final, run_started_at))

            prompt_metadata.update(completion.metadata or {})
            host.set_prompt_metadata(prompt_metadata)
            if self._handle_truncation(host, task_state, run_context, completion.metadata):
                continue
            if task_state.stop_reason:
                break

            kind, payload, parse_error_type = host.parse_with_metadata(completion.text)
            host.emit_trace(
                task_state,
                "model_parsed",
                {
                    "kind": kind,
                    "parse_error_type": parse_error_type,
                    "completion_metadata": completion.metadata,
                    "duration_ms": int((time.monotonic() - model_started_at) * 1000),
                },
            )
            result = self._dispatch_decision(
                host,
                task_state,
                run_context,
                user_message,
                completion.text,
                kind,
                payload,
                run_started_at,
            )
            if result is not None:
                return result

        final = self._stopped_final(task_state, run_context)
        task_state.stage = "stopped"
        return RunResult(
            host.finish_run(
                task_state,
                user_message,
                final,
                run_started_at,
                checkpoint_trigger=task_state.stop_reason or "run_stopped",
                promote_memory=True,
                assess_completion=True,
            )
        )

    def _build_prompt(self, host: RuntimeHost, task_state, user_message: str) -> tuple[str, dict]:
        prompt_started_at = time.monotonic()
        prompt, prompt_metadata = host.build_prompt_for_turn(user_message)
        auto_compaction = host.auto_compact_history(prompt_metadata)
        if auto_compaction.get("compacted"):
            host.emit_trace(task_state, "history_compacted", {"compaction": auto_compaction})
            prompt, prompt_metadata = host.build_prompt_for_turn(user_message)
            prompt_metadata["auto_compaction"] = auto_compaction
        host.emit_trace(
            task_state,
            "prompt_built",
            {
                "prompt_metadata": prompt_metadata,
                "duration_ms": int((time.monotonic() - prompt_started_at) * 1000),
            },
        )
        return prompt, prompt_metadata

    def _checkpoint_prompt_state(self, host: RuntimeHost, task_state, user_message: str, prompt_metadata: dict) -> None:
        if prompt_metadata.get("resume_status") == CHECKPOINT_PARTIAL_STALE_STATUS:
            self._checkpoint(host, task_state, user_message, "freshness_mismatch")
        elif prompt_metadata.get("resume_status") == CHECKPOINT_WORKSPACE_MISMATCH_STATUS:
            host.emit_trace(
                task_state,
                "runtime_identity_mismatch",
                {"fields": list(prompt_metadata.get("runtime_identity_mismatch_fields", []))},
            )
            self._checkpoint(host, task_state, user_message, "workspace_mismatch")
        if prompt_metadata.get("budget_reductions"):
            self._checkpoint(host, task_state, user_message, "context_reduction")

    def _checkpoint(self, host: RuntimeHost, task_state, user_message: str, trigger: str) -> None:
        checkpoint = host.create_checkpoint(task_state, user_message, trigger=trigger)
        host.write_task_state(task_state)
        host.emit_trace(
            task_state,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "trigger": trigger,
            },
        )

    def _handle_model_error(
        self,
        host: RuntimeHost,
        task_state,
        run_context,
        user_message: str,
        prompt_metadata: dict,
        exc: Exception,
        model_started_at: float,
    ) -> bool:
        completion_metadata = host.model_error_metadata(exc)
        if (
            host.is_recoverable_model_error(exc)
            and run_context.model_error_recovery_count < 3
            and run_context.attempts < run_context.max_attempts
        ):
            run_context.model_error_recovery_count += 1
            host.set_prompt_metadata({**prompt_metadata, **completion_metadata})
            host.emit_trace(
                task_state,
                "model_error_recovered",
                {
                    "completion_metadata": completion_metadata,
                    "duration_ms": int((time.monotonic() - model_started_at) * 1000),
                    "recovery_count": run_context.model_error_recovery_count,
                },
            )
            host.record(
                {
                    "role": "assistant",
                    "content": (
                        "Runtime notice: provider returned no usable text. "
                        "Retry once and emit exactly one valid tool call or final answer."
                    ),
                    "created_at": now(),
                }
            )
            host.write_task_state(task_state)
            return True
        prompt_metadata.update(completion_metadata)
        host.set_prompt_metadata(prompt_metadata)
        final = f"Stopped after model error: {exc}"
        task_state.stop_model_error(final)
        host.emit_trace(
            task_state,
            "model_error",
            {
                "completion_metadata": completion_metadata,
                "duration_ms": int((time.monotonic() - model_started_at) * 1000),
            },
        )
        return False

    def _handle_truncation(self, host: RuntimeHost, task_state, run_context, completion_metadata: dict) -> bool:
        if not host.is_truncated_completion(completion_metadata):
            return False
        run_context.truncation_recovery_count += 1
        if run_context.truncation_recovery_count <= 3:
            next_max_new_tokens = max(
                run_context.current_max_new_tokens * 4,
                run_context.current_max_new_tokens + 1024,
            )
            host.emit_trace(
                task_state,
                "truncation_recovered",
                {
                    "attempt": run_context.truncation_recovery_count,
                    "previous_max_new_tokens": run_context.current_max_new_tokens,
                    "next_max_new_tokens": next_max_new_tokens,
                    "completion_metadata": completion_metadata,
                },
            )
            run_context.current_max_new_tokens = next_max_new_tokens
            host.record(
                {
                    "role": "assistant",
                    "content": (
                        "Runtime notice: provider stopped because output was truncated. "
                        "Continue from the truncation and emit exactly one valid tool call or final answer."
                    ),
                    "created_at": now(),
                }
            )
            return True
        final = "Stopped after provider repeatedly truncated model output."
        task_state.stop_output_truncated(final)
        return False

    def _dispatch_decision(
        self,
        host: RuntimeHost,
        task_state,
        run_context,
        user_message: str,
        raw: str,
        kind: str,
        payload,
        run_started_at: float,
    ) -> RunResult | None:
        if kind == "tool":
            self._dispatch_tool(host, task_state, run_context, user_message, payload)
            return None
        if kind == "retry":
            host.record({"role": "assistant", "content": payload, "created_at": now()})
            host.write_task_state(task_state)
            return None
        return self._dispatch_final(host, task_state, run_context, user_message, raw, payload, run_started_at)

    def _dispatch_tool(self, host: RuntimeHost, task_state, run_context, user_message: str, payload: dict) -> None:
        name = payload.get("name", "")
        args = payload.get("args", {})
        control_decision = host.before_tool(task_state, name, args, user_message)
        host.record_control_decision(task_state, "before_tool", control_decision)
        forced_tool_result = None
        if control_decision.action == "remind":
            reminder_key = str(control_decision.reason)
            if reminder_key and host.runtime_reminder_once(reminder_key):
                host.emit_trace(
                    task_state,
                    "runtime_reminder_emitted",
                    {"reason": control_decision.reason, "message": control_decision.message, "tool": name, "args": args},
                )
                host.record({"role": "assistant", "content": control_decision.message, "created_at": now()})
        elif control_decision.action == "reject":
            forced_tool_result = control_decision.message
        host.execute_tool_request(
            task_state,
            run_context,
            user_message,
            name,
            args,
            forced_result=forced_tool_result,
        )

    def _dispatch_final(
        self,
        host: RuntimeHost,
        task_state,
        run_context,
        user_message: str,
        raw: str,
        payload,
        run_started_at: float,
    ) -> RunResult | None:
        final = (payload or raw).strip()
        host.drain_subagent_notifications()
        final_decision = host.before_final(task_state, final, user_message)
        host.record_control_decision(task_state, "before_final", final_decision)
        assessment = dict(final_decision.metadata.get("assessment", {}) or task_state.completion_gate or {})
        host.emit_trace(task_state, "completion_assessed", {"assessment": assessment, "proposed_final": final})
        if final_decision.action == "block_final":
            host.emit_trace(
                task_state,
                "completion_gate_blocked",
                {"decision": final_decision.to_dict(), "proposed_final": final},
            )
            host.record({"role": "assistant", "content": final_decision.message, "created_at": now()})
            if final_decision.next_tool and run_context.remaining_tool_steps > 0:
                host.execute_tool_request(
                    task_state,
                    run_context,
                    user_message,
                    final_decision.next_tool,
                    dict(final_decision.tool_args or {}),
                    source="runtime_control",
                    checkpoint_trigger="runtime_control_tool",
                )
            host.write_task_state(task_state)
            return None
        task_state.finish_success(final)
        return RunResult(
            host.finish_run(
                task_state,
                user_message,
                final,
                run_started_at,
                checkpoint_trigger="run_finished",
                promote_memory=True,
            )
        )

    def _stopped_final(self, task_state, run_context) -> str:
        if run_context.attempts >= run_context.max_attempts and run_context.tool_steps < run_context.max_steps:
            final = "Stopped after too many malformed model responses without a valid tool call or final answer."
            task_state.stop_retry_limit(final)
            return final
        if task_state.stop_reason:
            return task_state.final_answer or "Stopped before completion."
        final = "Stopped after reaching the step limit without a final answer."
        task_state.stop_step_limit(final)
        return final


def _cancelled(cancel_event) -> bool:
    return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())
