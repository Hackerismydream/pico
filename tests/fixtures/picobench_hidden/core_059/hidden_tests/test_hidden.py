from artifacts import *

def test_hidden_behavior():
    assert normalize_artifacts(['a', 'a', 'b'], workspace='/repo') == ['a', 'b']
