from secrets import secret_env_names


def test_detects_key_token_secret_names():
    env = {'OPENAI_API_KEY': 'x', 'PICO_TOKEN': 't', 'PATH': '/bin'}
    assert secret_env_names(env) == ['OPENAI_API_KEY', 'PICO_TOKEN']
