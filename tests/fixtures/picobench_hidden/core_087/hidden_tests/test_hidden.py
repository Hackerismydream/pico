from redactor import redact_provider_config


def test_missing_key_is_reported_false():
    redacted = redact_provider_config({'provider': 'x', 'protocol': 'openai', 'model': 'm', 'base_url': 'http://localhost:8000/v1'})
    assert redacted['has_api_key'] is False
    assert redacted['base_url_host'] == 'localhost:8000'
