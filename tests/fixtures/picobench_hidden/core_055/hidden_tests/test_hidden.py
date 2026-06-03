from sections import *

def test_hidden_behavior():
    assert render_sections([{'name': 'old', 'priority': 1, 'expired': True}]) == []
