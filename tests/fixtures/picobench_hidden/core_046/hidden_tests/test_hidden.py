from spans import validate_spans

def test_duplicate_span_ids_are_rejected():
    assert validate_spans([{'span_id': 's1', 'parent_span_id': ''}, {'span_id': 's1', 'parent_span_id': ''}]) is False
