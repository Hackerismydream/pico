from trace_summary import summarize_trace


def test_counts_tool_events_and_final_stop_reason():
    events = [
        {'event': 'tool_executed', 'name': 'read_file'},
        {'event': 'tool_executed', 'name': 'read_file'},
        {'event': 'run_finished', 'status': 'completed', 'stop_reason': 'final_answer_returned'},
    ]
    assert summarize_trace(events)['tool_name_counts'] == {'read_file': 2}
    assert summarize_trace(events)['stop_reason'] == 'final_answer_returned'
    assert summarize_trace(events)['error_count'] == 0
