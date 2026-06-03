import json


def load_config(path, defaults=None):
    with open(path, encoding="utf-8") as file:
        return json.load(file)
