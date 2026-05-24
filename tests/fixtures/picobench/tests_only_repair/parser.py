def parse_pair(text):
    key, value = text.split("=", 1)
    return key.strip(), value.strip()
