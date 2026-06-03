from matrix import *

def test_public_behavior():
    assert expand_matrix(['core_001'], ['deepseek', 'gpt']) == [('core_001', 'deepseek'), ('core_001', 'gpt')]
    assert expand_matrix(['core_002'], []) == [('core_002', 'default')]
    assert expand_matrix([], ['deepseek']) == []
