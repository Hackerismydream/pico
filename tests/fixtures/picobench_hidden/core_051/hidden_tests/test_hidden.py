from costs import *

def test_hidden_behavior():
    assert total_cost([{'input_tokens': 1000, 'rate': 0.001}, {}]) == 0.001
