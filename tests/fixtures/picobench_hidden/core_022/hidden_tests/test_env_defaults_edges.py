from env_defaults import get_setting


def test_get_setting_prefers_environment(monkeypatch):
    monkeypatch.setenv("PICO_TIMEOUT", "60")
    assert get_setting("PICO_TIMEOUT", default="30") == "60"
