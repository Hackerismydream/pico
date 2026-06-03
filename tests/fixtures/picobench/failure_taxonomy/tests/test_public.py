from taxonomy import *

def test_public_behavior():
    assert classify_failure('401 auth_error') == 'provider'
    assert classify_failure('missing trace evidence') == 'evidence'
    assert classify_failure('process timed out after 300s') == 'timeout'
