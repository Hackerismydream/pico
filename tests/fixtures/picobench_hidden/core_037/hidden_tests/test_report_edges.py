from report import build_report


def test_report_detects_failed_event():
    report = build_report([{"type": "started"}, {"type": "failed"}])
    assert report["status"] == "failed"
    assert report["trace_summary"]["failed"] == 1


def test_report_handles_empty_trace():
    assert build_report([]) == {
        "status": "running",
        "trace_summary": {"started": 0, "finished": 0, "failed": 0},
    }
