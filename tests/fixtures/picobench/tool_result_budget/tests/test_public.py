from tool_result import render_tool_result

def test_long_output_keeps_head_and_marks_artifact():
    result = render_tool_result('abcdefghijklmnopqrstuvwxyz', limit=10)
    assert result['inline'] == 'abcdefghij'
    assert result['artifact_required'] is True
