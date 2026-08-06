from types import SimpleNamespace

from pico.providers.litellm_provider import LiteLLMProvider


def test_parse_response_preserves_actual_model_identity() -> None:
    provider = LiteLLMProvider.__new__(LiteLLMProvider)
    response = SimpleNamespace(
        model="deepseek-v4-flash",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ready",
                    tool_calls=[],
                    reasoning_content=None,
                    thinking_blocks=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
            prompt_tokens_details=None,
        ),
    )

    parsed = provider._parse_response(response)

    assert parsed.model == "deepseek-v4-flash"


def test_parse_response_normalizes_deepseek_cache_usage() -> None:
    provider = LiteLLMProvider.__new__(LiteLLMProvider)
    response = SimpleNamespace(
        model="deepseek-v4-flash",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ready",
                    tool_calls=[],
                    reasoning_content=None,
                    thinking_blocks=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=4090,
            completion_tokens=8,
            total_tokens=4098,
            prompt_cache_hit_tokens=3968,
            prompt_cache_miss_tokens=122,
            prompt_tokens_details=None,
        ),
    )

    parsed = provider._parse_response(response)

    assert parsed.usage == {
        "prompt_tokens": 4090,
        "completion_tokens": 8,
        "total_tokens": 4098,
        "cache_read_input_tokens": 3968,
        "cache_miss_input_tokens": 122,
    }
