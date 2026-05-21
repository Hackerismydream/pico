from logger import log_request


def test_api_key_is_redacted_from_log_message():
    message = log_request("ada", "sk-live-secret")

    assert "sk-live-secret" not in message
    assert "[REDACTED]" in message
    assert "ada" in message
