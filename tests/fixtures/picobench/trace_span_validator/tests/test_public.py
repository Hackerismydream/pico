from spans import validate_spans

def test_parent_span_must_exist_before_child():
    events = [{'span_id': 's2', 'parent_span_id': 's1'}, {'span_id': 's1', 'parent_span_id': ''}]
    assert validate_spans(events) is False

def test_valid_root_and_child_span_passes():
    assert validate_spans([{'span_id': 's1', 'parent_span_id': ''}, {'span_id': 's2', 'parent_span_id': 's1'}]) is True
