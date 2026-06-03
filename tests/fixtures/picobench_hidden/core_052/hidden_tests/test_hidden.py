from taxonomy import *

def test_hidden_behavior():
    assert classify_failure('process timed out after 300s') == 'timeout'
