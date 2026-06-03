from handoff_check import validate_handoff


def test_list_fields_must_be_lists():
    bad = {'intent': 'fix', 'changed_paths': 'a.py', 'tests_run': [], 'evidence_paths': [], 'open_risks': []}
    assert validate_handoff(bad) is False
