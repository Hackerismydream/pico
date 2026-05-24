from cli import build_config


def test_default_config_includes_timeout_and_retries():
    assert build_config([]) == {"timeout": 30, "retries": 1}


def test_cli_overrides_only_selected_values():
    assert build_config(["--timeout", "5"]) == {"timeout": 5, "retries": 1}
