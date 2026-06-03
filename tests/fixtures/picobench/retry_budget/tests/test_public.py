from retry_budget import *

def test_public_behavior():
    b = RetryBudget(2)
    assert b.allow('empty_response') is True
    assert b.allow('empty_response') is True
    assert b.allow('empty_response') is False
