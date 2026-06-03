from sandbox_policy import parse_network_policy

def test_allowlist_hosts_are_trimmed():
    assert parse_network_policy('allow: api.deepseek.com, example.com ') == {'mode': 'allow', 'hosts': ['api.deepseek.com', 'example.com']}
