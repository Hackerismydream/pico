from failure_report import render_failure_report


def test_empty_message_still_lists_check_name():
    assert 'bad' in render_failure_report({'task_id': 't', 'failure_category': 'x', 'checks': [{'name': 'bad', 'passed': False}]})
