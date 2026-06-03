from failure_report import render_failure_report


def test_report_contains_failed_check_only():
    text = render_failure_report({'task_id': 'core_x', 'failure_category': 'hidden', 'checks': [{'name': 'ok', 'passed': True}, {'name': 'bad', 'passed': False, 'message': 'no'}]})
    assert 'core_x' in text and 'hidden' in text and 'bad' in text and 'no' in text
    assert 'ok' not in text
