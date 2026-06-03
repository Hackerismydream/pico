from checks import aggregate_checks


def test_failed_check_sets_strict_failure_and_category():
    result = aggregate_checks([{'passed': True}, {'passed': False, 'failure_category': 'hidden_test_failure'}])
    assert result['strict_pass'] is False
    assert result['failure_category'] == 'hidden_test_failure'
    assert result['failed'] == 1
