from pico.providers.adapter import (
    is_recoverable_error,
    is_truncated,
    normalize_completion_metadata,
)


def test_provider_adapter_normalizes_finish_and_stop_reason():
    metadata = normalize_completion_metadata(
        {"stop_reason": "max_tokens", "input_tokens": 10, "output_tokens": 20},
        transport="anthropic_sdk",
    )

    assert metadata["finish_reason"] == "max_tokens"
    assert metadata["stop_reason"] == "max_tokens"
    assert metadata["provider_transport"] == "anthropic_sdk"
    assert is_truncated(metadata)


def test_provider_adapter_classifies_recoverable_empty_provider_text():
    assert is_recoverable_error(ValueError("could not extract text from event stream response"))
