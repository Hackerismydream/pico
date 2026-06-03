from truncation import truncate_output


def test_long_output_marks_truncation_and_omitted_chars():
    result = truncate_output('abcdefghij', limit=6)
    assert result['truncated'] is True
    assert result['omitted_chars'] == 4
