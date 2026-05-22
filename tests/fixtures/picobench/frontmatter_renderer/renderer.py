from parser import parse_document


def render_summary(text):
    doc = parse_document(text)
    return doc["body"].splitlines()[0]
