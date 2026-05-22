from emailer import is_valid_email


def test_email_requires_single_at_and_domain_dot():
    assert is_valid_email("dev@example.com")
    assert not is_valid_email("dev@@example.com")
    assert not is_valid_email("dev@example")
