from phase_gate import *

def test_public_behavior():
    assert can_finish('edit', verified=False) is False
    assert can_finish('edit', verified=True) is True
