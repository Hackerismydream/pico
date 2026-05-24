from redact import redact_payload


def test_redacts_secrets_inside_lists():
    payload = {"items": [{"password": "pw"}, {"name": "ok"}]}
    assert redact_payload(payload) == {"items": [{"password": "***"}, {"name": "ok"}]}


def test_does_not_mutate_original_payload():
    payload = {"config": {"api_key": "secret"}}
    redacted = redact_payload(payload)
    assert redacted["config"]["api_key"] == "***"
    assert payload["config"]["api_key"] == "secret"
