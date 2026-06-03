from policy_61 import normalize

def test_normalize_strips_and_maps_none():
    assert normalize('  ALLOW  ') == 'allow'
    assert normalize(None) == ''
