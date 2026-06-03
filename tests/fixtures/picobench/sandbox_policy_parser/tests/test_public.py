from sandbox_policy import parse_network_policy

def test_off_aliases_disable_network():
    assert parse_network_policy('off') == {'mode': 'none', 'hosts': []}
    assert parse_network_policy('deny') == {'mode': 'none', 'hosts': []}
