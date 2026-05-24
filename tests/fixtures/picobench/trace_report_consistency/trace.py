def summarize_events(events):
    return {
        "started": len([event for event in events if event["type"] == "started"]),
        "finished": len([event for event in events if event["type"] == "finished"]),
    }
