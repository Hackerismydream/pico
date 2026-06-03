def parse_todos(text):
    return [line.strip() for line in text.splitlines() if line.strip()]
