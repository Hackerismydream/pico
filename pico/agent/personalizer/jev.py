"""Bounded TypeSafe client for Personalizer, not a chat Provider or authorization gate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any

import httpx

from pico.agent.personalizer.jev_policy import (
    POLICY_VERSION,
    QUESTION_VERSION,
    QUESTIONS,
    DecisionContractError,
    GateDecision,
    evaluate_answers,
)
from pico.tracing import trace

if TYPE_CHECKING:
    from pico.call_efficiency import CallEfficiency
    from pico.config.personalization import PersonalizationGateConfig

_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
_RESPONSE_LIMIT = 65_536


class _ApiError(Exception):
    def __init__(self, status: int):
        self.status = status


class JevPreferenceGate:
    def __init__(
        self,
        config: PersonalizationGateConfig,
        accounting: CallEfficiency,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config.model_copy(deep=True)
        self.accounting = accounting
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._slots = asyncio.Semaphore(config.max_concurrent)
        self._pending: set[asyncio.Task[GateDecision]] = set()
        self._requests: deque[float] = deque()
        self._failures = 0
        self._open_until = 0.0
        self._permanent_fault = False
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def assess(self, message: str, history: list[dict], memory: str) -> GateDecision:
        with trace.span("personalize.jev", kind="model") as span:
            result = await self._assess(message, history, memory)
            span.set(
                {
                    "decision.reason": result.reason,
                    "decision.fast_pass": result.fast_pass,
                    "decision.would_fast_pass": result.would_fast_pass,
                    "decision.call_id": result.call_id,
                    "decision.mode": self.config.mode,
                }
            )
            return result

    async def _assess(self, message: str, history: list[dict], memory: str) -> GateDecision:
        if self.config.mode == "off":
            return GateDecision(reason="off")
        if self._closed:
            return GateDecision(reason="closed")
        if self.accounting.mode == "off" or not self.accounting.ledger.persist:
            return GateDecision(reason="accounting_unavailable")
        if not message.strip():
            return GateDecision(reason="empty_message")
        # Never give the fast path a silently truncated or non-text view.
        if len(history) > 4 or any(
            not isinstance(item, dict)
            or not isinstance(item.get("content", ""), str)
            or len(item.get("content", "")) > 200
            for item in history
        ):
            return GateDecision(reason="unsupported_history")
        from pico.agent.personalizer.personalizer import Personalizer

        state = {
            "message": message,
            "known_preferences": memory or "(empty)",
            "recent_conversation": Personalizer._format_history(history) if history else "(no prior context)",
        }
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > self.config.max_state_bytes:
            return GateDecision(reason="state_too_large")
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            return GateDecision(reason="missing_credentials")
        now = time.monotonic()
        if self._permanent_fault or now < self._open_until:
            return GateDecision(reason="circuit_open")
        while self._requests and now - self._requests[0] >= 60:
            self._requests.popleft()
        if len(self._requests) >= self.config.requests_per_minute:
            return GateDecision(reason="local_rate_limit")
        if self._slots.locked():
            return GateDecision(reason="capacity")
        async with self._slots:
            if self._closed:
                return GateDecision(reason="closed")
            self._requests.append(now)
            task = asyncio.create_task(self._evaluate(state, encoded, api_key))
            self._pending.add(task)
            try:
                return await task
            finally:
                self._pending.discard(task)

    async def _post(self, state: dict[str, str], api_key: str) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
                timeout=self.config.timeout_seconds,
                limits=httpx.Limits(max_connections=self.config.max_concurrent),
            )
        async with self._client.stream(
            "POST",
            _ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"state": state, "model": self.config.model, "questions": QUESTIONS},
        ) as response:
            if response.status_code != 200:
                raise _ApiError(response.status_code)
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > _RESPONSE_LIMIT:
                    raise DecisionContractError("response_too_large")
        payload = json.loads(chunks)
        if not isinstance(payload, dict):
            raise DecisionContractError("response_type")
        return payload

    async def _evaluate(self, state: dict[str, str], encoded: bytes, api_key: str) -> GateDecision:
        started = time.monotonic()
        call_id = uuid.uuid4().hex
        actual_model: str | None = None
        usage: Any = None
        outcome = "error"
        reason = "transport_error"
        answers: dict[str, Any] = {}
        would_pass = False
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                payload = await self._post(state, api_key)
                usage = payload.get("usage")
                reported_model = payload.get("model")
                actual_model = (
                    reported_model if isinstance(reported_model, str) and len(reported_model) <= 100 else None
                )
                if actual_model != self.config.model:
                    raise DecisionContractError("model_mismatch")
                would_pass, reason, answers = evaluate_answers(
                    payload.get("answers"),
                    min_confidence=self.config.min_confidence,
                    min_choice_probability=self.config.min_choice_probability,
                )
                if not _complete_usage(usage):
                    would_pass, reason = False, "usage_incomplete"
                outcome = "success"
                self._failures = 0
        except asyncio.CancelledError:
            outcome, reason = "cancelled", "cancelled"
            raise
        except (TimeoutError, httpx.TimeoutException):
            reason = "timeout"
        except _ApiError as exc:
            reason = f"http_{exc.status}"
            if exc.status in {401, 403, 422}:
                self._permanent_fault = True
        except DecisionContractError as exc:
            reason = str(exc)
        except (httpx.HTTPError, ValueError, UnicodeError):
            reason = "transport_or_json_error"
        except Exception:
            # Do not log vendor bodies, credentials, preference text or exception payloads.
            reason = "client_error"
        finally:
            if outcome == "error":
                self._failures += 1
                if self._failures >= self.config.failure_threshold:
                    self._open_until = time.monotonic() + self.config.cooldown_seconds
            ctx = trace.current()
            try:
                record = self.accounting.record_external(
                    call_id=call_id,
                    requested_model=self.config.model,
                    actual_model=actual_model,
                    raw_usage=usage,
                    outcome=outcome,
                    error_category=reason if outcome != "success" else None,
                    duration_ms=(time.monotonic() - started) * 1000,
                    session_key=getattr(ctx, "session_key", None),
                    trace_id=getattr(ctx, "trace_id", None),
                    turn_span_id=getattr(ctx, "turn_span_id", None),
                    details={
                        "purpose": "personalize.classify",
                        "question_version": QUESTION_VERSION,
                        "policy_version": POLICY_VERSION,
                        "policy_digest": self.config.policy_digest,
                        "mode": self.config.mode,
                        "state_sha256": hashlib.sha256(encoded).hexdigest(),
                        "state_bytes": len(encoded),
                        "reason": reason,
                        "would_fast_pass": would_pass,
                        "min_confidence": self.config.min_confidence,
                        "min_choice_probability": self.config.min_choice_probability,
                        "answers": answers,
                    },
                )
                if "ledger_write_failed" in record.findings:
                    would_pass, reason = False, "ledger_write_failed"
            except Exception:
                would_pass, reason = False, "accounting_error"
        return GateDecision(
            fast_pass=would_pass and self.config.mode == "enforce",
            reason=reason,
            would_fast_pass=would_pass,
            call_id=call_id,
        )

    def begin_close(self) -> None:
        self._closed = True
        for task in tuple(self._pending):
            task.cancel()

    async def aclose(self) -> None:
        async with self._close_lock:
            self.begin_close()
            if self._pending:
                await asyncio.gather(*tuple(self._pending), return_exceptions=True)
            if self._client is not None:
                await self._client.aclose()
                self._client = None


def _complete_usage(usage: Any) -> bool:
    return isinstance(usage, dict) and all(
        type(usage.get(key)) is int and 0 <= usage[key] < 2**53 for key in ("input_tokens", "output_tokens")
    )
