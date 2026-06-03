from emailer import is_valid_email


def test_email_rejects_empty_parts_and_spaces():
    assert not is_valid_email("@example.com")
    assert not is_valid_email("dev @example.com")
