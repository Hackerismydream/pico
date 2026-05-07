"""Conversation compaction helpers for Pico."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .context_usage import context_window_for_model, estimate_tokens
from ..core.workspace import clip, now


AUTOCOMPACT_BUFFER_TOKENS = 13_000
COMPACT_MAX_OUTPUT_TOKENS = 4096
MIN_RECENT_MESSAGES = 6
MIN_RECENT_TOKENS = 10_000


def history_text(history):
    lines = []
    for item in history:
        if item.get("role") == "tool":
            lines.append(f"[tool:{item.get('name', 'tool')}] {json.dumps(item.get('args', {}), sort_keys=True)}")
            lines.append(str(item.get("content", "")))
        else:
            lines.append(f"[{item.get('role', 'unknown')}] {item.get('content', '')}")
    return "\n".join(lines)


def deterministic_summary(history):
    lines = ["Summary of compacted earlier history:"]
    for item in history:
        role = str(item.get("role", "unknown"))
        if role == "tool":
            name = str(item.get("name", "tool"))
            args = json.dumps(item.get("args", {}), sort_keys=True, ensure_ascii=True)
            content = clip(item.get("content", ""), 260)
            lines.append(f"- tool:{name} {args} -> {content}")
        else:
            lines.append(f"- {role}: {clip(item.get('content', ''), 260)}")
    return "\n".join(lines)


def auto_compact_threshold(model, override_tokens=None):
    if override_tokens is not None:
        return max(1, int(override_tokens))
    window = context_window_for_model(model)
    summary_reserve = min(20_000, window // 5)
    return max(1, window - summary_reserve - AUTOCOMPACT_BUFFER_TOKENS)


def _message_tokens(item):
    if item.get("role") == "tool":
        text = f"{item.get('name', 'tool')} {json.dumps(item.get('args', {}), sort_keys=True)} {item.get('content', '')}"
    else:
        text = str(item.get("content", ""))
    return estimate_tokens(text)


def split_recent_for_auto(history, min_recent_messages=MIN_RECENT_MESSAGES, min_recent_tokens=MIN_RECENT_TOKENS):
    history = list(history)
    if len(history) <= min_recent_messages:
        return [], history

    keep_start = len(history)
    kept_messages = 0
    kept_tokens = 0
    for index in range(len(history) - 1, -1, -1):
        kept_messages += 1
        kept_tokens += _message_tokens(history[index])
        keep_start = index
        if kept_messages >= min_recent_messages and kept_tokens >= min_recent_tokens:
            break

    return history[:keep_start], history[keep_start:]


def split_recent_manual(history, keep_recent):
    keep_recent = max(1, int(keep_recent or MIN_RECENT_MESSAGES))
    history = list(history)
    if len(history) <= keep_recent:
        return [], history
    return history[:-keep_recent], history[-keep_recent:]


@dataclass
class CompactService:
    model_client: object
    model_name: str = ""
    min_recent_messages: int = MIN_RECENT_MESSAGES
    min_recent_tokens: int = MIN_RECENT_TOKENS
    max_summary_tokens: int = COMPACT_MAX_OUTPUT_TOKENS
    auto_threshold_override_tokens: int | None = None

    def should_auto_compact(self, prompt_metadata):
        usage = dict(prompt_metadata.get("context_usage", {}) or {})
        prompt_tokens = int(usage.get("estimated_prompt_tokens") or 0)
        threshold = auto_compact_threshold(self.model_name, self.auto_threshold_override_tokens)
        return prompt_tokens >= threshold, threshold, prompt_tokens

    def compact(self, history, trigger, keep_recent=None, summary=None, use_model_summary=True):
        history = list(history)
        if keep_recent is None:
            old_history, recent = split_recent_for_auto(
                history,
                min_recent_messages=self.min_recent_messages,
                min_recent_tokens=self.min_recent_tokens,
            )
        else:
            old_history, recent = split_recent_manual(history, keep_recent)

        before_text = history_text(history)
        before_tokens = estimate_tokens(before_text)
        before_count = len(history)
        if not old_history:
            return {
                "compacted": False,
                "reason": "too_few_messages",
                "before_messages": before_count,
                "after_messages": before_count,
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "summary_chars": 0,
                "summary_source": "none",
                "trigger": trigger,
            }

        summary_text, summary_source, error = self._summary_text(old_history, summary, use_model_summary)
        compact_item = {
            "role": "assistant",
            "content": "[compacted context]\n" + summary_text,
            "created_at": now(),
            "compacted": True,
            "compaction": {
                "trigger": trigger,
                "summary_source": summary_source,
                "before_messages": before_count,
                "summary_chars": len(summary_text),
            },
        }
        new_history = [compact_item, *recent]
        after_tokens = estimate_tokens(history_text(new_history))
        return {
            "compacted": True,
            "history": new_history,
            "trigger": trigger,
            "before_messages": before_count,
            "after_messages": len(new_history),
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "summary_chars": len(summary_text),
            "summary_source": summary_source,
            "error": error,
        }

    def _summary_text(self, history, summary, use_model_summary):
        supplied = str(summary).strip() if summary else ""
        if supplied:
            return supplied, "provided", ""
        if use_model_summary:
            try:
                model_summary = str(self.model_client.complete(self._summary_prompt(history), self.max_summary_tokens)).strip()
                if model_summary:
                    return model_summary, "model", ""
            except Exception as exc:
                return deterministic_summary(history), "deterministic_fallback", f"{exc.__class__.__name__}: {exc}"
        return deterministic_summary(history), "deterministic", ""

    def _summary_prompt(self, history):
        rendered = []
        for item in history:
            if item.get("role") == "tool":
                args = json.dumps(item.get("args", {}), sort_keys=True, ensure_ascii=True)
                rendered.append(f"[tool:{item.get('name', 'tool')}] {args}\n{clip(item.get('content', ''), 1200)}")
            else:
                rendered.append(f"[{item.get('role', 'unknown')}] {clip(item.get('content', ''), 1200)}")
        transcript = "\n\n".join(rendered)
        return (
            "Summarize the compacted Pico conversation history so the agent can continue the task.\n"
            "Return only the summary. Preserve concrete file paths, commands, errors, decisions, current work, and next steps.\n\n"
            "Use these sections:\n"
            "Primary Request\n"
            "Key Technical Concepts\n"
            "Files and Code\n"
            "Errors and Fixes\n"
            "Current Work\n"
            "Pending Tasks\n\n"
            "Compacted transcript:\n"
            f"{transcript}"
        )
