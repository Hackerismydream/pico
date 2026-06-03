SECRET_KEYS = {"api_key", "token", "password"}


def redact_payload(payload):
    redacted = {}
    for key, value in payload.items():
        if key in SECRET_KEYS:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted
