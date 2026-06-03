from pathlib import Path


def normalize_path(root, user_path):
    return Path(root) / user_path
