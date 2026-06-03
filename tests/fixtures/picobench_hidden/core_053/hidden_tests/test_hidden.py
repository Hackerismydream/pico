from handoff import *

def test_hidden_behavior():
    assert build_handoff('x', None, None)['constraints'] == []
