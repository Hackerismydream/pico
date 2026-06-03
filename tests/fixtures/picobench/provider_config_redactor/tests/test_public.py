from redactor import redact_provider_config


def test_redacts_api_key_and_keeps_host():
    redacted = redact_provider_config({'provider': 'deepseek', 'protocol': 'anthropic', 'model': 'm', 'base_url': 'https://api.deepseek.com/anthropic', 'api_key': 'secret'})
    assert redacted['has_api_key'] is True
    assert redacted['base_url_host'] == 'api.deepseek.com'
    assert 'api_key' not in redacted

def test_host_keeps_port_when_present():
    redacted = redact_provider_config({'provider': 'local', 'protocol': 'openai', 'model': 'm', 'base_url': 'http://localhost:8000/v1'})
    assert redacted['base_url_host'] == 'localhost:8000'
