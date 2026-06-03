from session_events import filter_events


def test_none_run_filter_can_filter_by_event_only():
    events = [{'run_id': 'r1', 'event': 'b'}, {'run_id': 'r2', 'event': 'a'}]
    assert filter_events(events, event='a') == [{'run_id': 'r2', 'event': 'a'}]
