import json
from config_loader import load_config


def test_load_config_merges_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"timeout": 10}), encoding="utf-8")
    assert load_config(path, defaults={"timeout": 3, "retries": 2}) == {"timeout": 10, "retries": 2}
