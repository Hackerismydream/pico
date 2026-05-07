"""Token-level context accounting helpers."""

from __future__ import annotations

import math


DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
MODEL_CONTEXT_WINDOWS = {
    "gpt-5": 400_000,
    "gpt-5.": 400_000,
    "claude": 200_000,
    "deepseek": 128_000,
    "qwen": 32_000,
}


def estimate_tokens_from_chars(char_count):
    """Return a conservative prompt-token estimate from rendered character count."""
    char_count = max(0, int(char_count or 0))
    if char_count == 0:
        return 0
    return max(1, math.ceil(char_count / 4))


def estimate_tokens(text):
    return estimate_tokens_from_chars(len(str(text or "")))


def context_window_for_model(model, default=DEFAULT_CONTEXT_WINDOW_TOKENS):
    model_name = str(model or "").lower()
    for marker, window in MODEL_CONTEXT_WINDOWS.items():
        if marker in model_name:
            return window
    return int(default)


def build_context_usage(prompt, metadata, model, reserved_output_tokens):
    sections = dict(metadata.get("sections", {}) or {})
    section_tokens = {
        section: estimate_tokens_from_chars(details.get("rendered_chars", 0))
        for section, details in sections.items()
    }
    prompt_tokens = estimate_tokens(prompt)
    reserved_output_tokens = max(0, int(reserved_output_tokens or 0))
    window = context_window_for_model(model)
    available = max(0, window - reserved_output_tokens)
    return {
        "estimated_prompt_tokens": prompt_tokens,
        "model_context_window_tokens": window,
        "reserved_output_tokens": reserved_output_tokens,
        "available_prompt_tokens": available,
        "estimated_total_tokens": prompt_tokens + reserved_output_tokens,
        "budget_status": "ok" if prompt_tokens <= available else "over_budget",
        "section_estimated_tokens": section_tokens,
    }
