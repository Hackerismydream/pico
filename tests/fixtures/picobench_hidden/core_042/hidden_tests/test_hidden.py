from tool_result import render_tool_result

def test_exact_limit_and_zero_limit_edges():
    assert render_tool_result('12345', limit=5) == {'inline': '12345', 'artifact_required': False}
    assert render_tool_result('12345', limit=0) == {'inline': '', 'artifact_required': True}
