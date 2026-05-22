import json


def load_config(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def resolve_timeout(path, env, cli_timeout=None):
    return load_config(path).get("timeout", 30)
