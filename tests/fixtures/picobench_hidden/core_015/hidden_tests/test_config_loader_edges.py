import json
from config_loader import load_config


def test_load_config_does_not_mutate_defaults(tmp_path):
    defaults = {"debug": False}
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    loaded = load_config(path, defaults=defaults)
    loaded["debug"] = True
    assert defaults == {"debug": False}


def test_empty_config_returns_defaults_copy(tmp_path):
    defaults = {"debug": False}
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    assert load_config(path, defaults=defaults) == {"debug": False}
