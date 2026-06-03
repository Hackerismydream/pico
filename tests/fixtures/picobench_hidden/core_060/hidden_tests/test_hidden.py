from matrix import *

def test_hidden_behavior():
    assert expand_matrix(['t'], []) == [('t', 'default')]
