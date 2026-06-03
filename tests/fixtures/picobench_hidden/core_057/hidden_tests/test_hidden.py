from phase_gate import *

def test_hidden_behavior():
    assert can_finish('edit', blocked_reason='provider unavailable') is False
    assert can_finish('final', blocked_reason='provider unavailable') is True
