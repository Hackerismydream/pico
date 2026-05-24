from config import env_value


def provider_config(env, provider):
    prefix = provider.upper()
    return {
        "api_key": env_value(env, f"{prefix}_API_KEY"),
        "model": env_value(env, f"{prefix}_MODEL"),
    }
