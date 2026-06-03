import json
from cli import main


def test_config_default_when_no_env_or_cli(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}), encoding="utf-8")
    assert main(["--config", str(config)], {}) == 30


def test_env_overrides_config_when_cli_absent(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"timeout": 7}), encoding="utf-8")
    assert main(["--config", str(config)], {"APP_TIMEOUT": "40"}) == 40
