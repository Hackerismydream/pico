from redact import redact_payload


def test_redacts_top_level_secret():
    assert redact_payload({"api_key": "sk-live", "name": "demo"}) == {
        "api_key": "***",
        "name": "demo",
    }


def test_redacts_nested_dictionary_secret():
    payload = {"config": {"token": "tok-1", "region": "us"}}
    assert redact_payload(payload) == {"config": {"token": "***", "region": "us"}}
