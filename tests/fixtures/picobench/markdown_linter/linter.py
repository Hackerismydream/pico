def lint_markdown(text):
    errors = []
    for index, line in enumerate(text.splitlines(), start=1):
        if line.endswith(" "):
            errors.append((index, "trailing-space"))
        if line.startswith("#") and not line.startswith("# "):
            errors.append((index, "bad-heading"))
    return errors


def has_errors(text):
    return len(lint_markdown(text)) > 0
