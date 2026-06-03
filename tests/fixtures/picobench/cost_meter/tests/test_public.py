from costs import *

def test_public_behavior():
    assert total_cost([{'input_tokens': 1000, 'output_tokens': 500, 'rate': 0.002}]) == 0.003
