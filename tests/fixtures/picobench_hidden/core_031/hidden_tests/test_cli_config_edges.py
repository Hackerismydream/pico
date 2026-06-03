from cli import build_config


def test_retries_can_be_overridden_without_losing_timeout():
    assert build_config(["--retries", "4"]) == {"timeout": 30, "retries": 4}


def test_zero_timeout_is_a_valid_explicit_cli_value():
    assert build_config(["--timeout", "0", "--retries", "2"]) == {"timeout": 0, "retries": 2}


def test_default_retries_are_present_without_cli_flags():
    assert build_config([])["retries"] == 1
