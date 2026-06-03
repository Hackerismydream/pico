def truncate_output(text, limit):
    return {'text': text[:limit], 'truncated': False, 'omitted_chars': 0}
