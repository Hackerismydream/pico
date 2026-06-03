from retry_budget import *

def test_hidden_behavior():
    b = RetryBudget(1)
    assert b.allow('a') is True
    assert b.allow('a') is False
    assert b.allow('b') is True
