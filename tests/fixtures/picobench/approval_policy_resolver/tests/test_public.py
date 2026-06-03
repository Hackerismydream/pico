from approval_policy import should_request_approval


def test_ask_policy_requests_only_high_risk():
    assert should_request_approval('ask', 'high') is True
    assert should_request_approval('ask', 'low') is False
