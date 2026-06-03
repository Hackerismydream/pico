from truncation import truncate_output


def test_long_output_contains_omitted_marker():
    result = truncate_output('abcdefghijkl', limit=8)
    assert result['truncated'] is True
    assert 'omitted' in result['text']
