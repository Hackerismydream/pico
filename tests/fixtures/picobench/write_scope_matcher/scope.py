def allowed_write(path, scopes):
    return any(path.startswith(scope) for scope in scopes)
