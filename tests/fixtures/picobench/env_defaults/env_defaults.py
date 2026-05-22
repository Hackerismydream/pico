import os


def get_setting(name, default=None):
    return os.environ[name]
