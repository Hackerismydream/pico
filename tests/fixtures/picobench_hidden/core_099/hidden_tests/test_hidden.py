from approval_policy import should_request_approval


def test_never_policy_and_auto_destructive_cases():
    assert should_request_approval('never', 'high', destructive=True) is False
    assert should_request_approval('auto', 'low', destructive=True) is True
