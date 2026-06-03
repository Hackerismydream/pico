from bundle import verify_bundle

def test_requires_report_and_task_state_for_complete_bundle():
    complete = {'summary.json','run_manifest.json','provider_config_redacted.json','trace.jsonl','report.json','task_state.json'}
    missing_report = complete - {'report.json'}
    missing_state = complete - {'task_state.json'}
    assert verify_bundle(complete) is True
    assert verify_bundle(missing_report) is False
    assert verify_bundle(missing_state) is False
