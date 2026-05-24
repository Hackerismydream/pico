from trace import summarize_events


def build_report(events):
    summary = summarize_events(events)
    return {"status": "completed" if summary["finished"] else "running"}
