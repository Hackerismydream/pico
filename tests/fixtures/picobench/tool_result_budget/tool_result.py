# tool_result.py
def render_tool_result(text, limit=20):
    text = str(text)
    return {'inline': text[-limit:], 'artifact_required': False}
