from logger import log_request


def test_empty_key_does_not_add_redaction_marker():
    assert log_request("ada", "") == "user=ada"
