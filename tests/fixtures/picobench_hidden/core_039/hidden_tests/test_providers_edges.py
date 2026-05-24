from providers import provider_config


def test_provider_specific_model_wins_over_default_model():
    env = {"PICO_DEFAULT_MODEL": "base", "DEEPSEEK_API_KEY": "k", "DEEPSEEK_MODEL": "reasoner"}
    assert provider_config(env, "deepseek") == {"api_key": "k", "model": "reasoner"}


def test_missing_api_key_is_explicit_none():
    assert provider_config({"PICO_DEFAULT_MODEL": "base"}, "anthropic") == {"api_key": None, "model": "base"}
