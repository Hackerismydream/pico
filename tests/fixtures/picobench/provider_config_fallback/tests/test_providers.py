from providers import provider_config


def test_provider_uses_provider_specific_key_and_model():
    env = {"DEEPSEEK_API_KEY": "k1", "DEEPSEEK_MODEL": "chat"}
    assert provider_config(env, "deepseek") == {"api_key": "k1", "model": "chat"}


def test_provider_model_falls_back_to_default_model():
    env = {"OPENAI_API_KEY": "k2", "PICO_DEFAULT_MODEL": "gpt"}
    assert provider_config(env, "openai") == {"api_key": "k2", "model": "gpt"}
