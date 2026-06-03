from env_defaults import get_setting


def test_get_setting_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("PICO_TIMEOUT", raising=False)
    assert get_setting("PICO_TIMEOUT", default="30") == "30"
