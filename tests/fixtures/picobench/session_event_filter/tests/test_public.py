from session_events import filter_events


def test_filters_by_run_and_event_name():
    events = [{'run_id': 'r1', 'event': 'a'}, {'run_id': 'r2', 'event': 'a'}, {'run_id': 'r1', 'event': 'b'}]
    assert filter_events(events, run_id='r1', event='a') == [{'run_id': 'r1', 'event': 'a'}]
