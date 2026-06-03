from handoff_check import validate_handoff


def test_complete_handoff_passes_and_missing_field_fails():
    handoff = {'intent': 'fix', 'changed_paths': ['a.py'], 'tests_run': ['pytest'], 'evidence_paths': ['report.json'], 'open_risks': []}
    assert validate_handoff(handoff) is True
    assert validate_handoff({'intent': 'fix'}) is False
