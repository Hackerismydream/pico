from paths import normalize_path


def is_allowed(root, user_path):
    path = normalize_path(root, user_path)
    return str(path).startswith(str(root))
