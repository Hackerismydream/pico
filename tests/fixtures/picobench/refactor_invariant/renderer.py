from parser import parse_items


def render_items(text):
    return "\n".join(f"- {item}" for item in parse_items(text))
