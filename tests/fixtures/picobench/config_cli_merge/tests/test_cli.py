import json
from cli import main


def test_cli_timeout_precedence(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"timeout": 10}), encoding="utf-8")
    assert main(["--config", str(config)], {"APP_TIMEOUT": "20"}) == 20
    assert main(["--config", str(config), "--timeout", "5"], {"APP_TIMEOUT": "20"}) == 5
