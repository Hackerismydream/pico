from trace_summary import summarize_trace


def test_counts_non_empty_error_codes():
    events = [{'event': 'tool_executed', 'name': 'x', 'error_code': 'denied'}, {'event': 'tool_executed', 'name': 'x', 'error_code': ''}]
    assert summarize_trace(events)['error_count'] == 1
