from report import build_report


def test_report_includes_trace_counts():
    report = build_report([{"type": "started"}, {"type": "finished"}])
    assert report["trace_summary"] == {"started": 1, "finished": 1}


def test_report_status_matches_finished_event():
    assert build_report([{"type": "started"}])["status"] == "running"
