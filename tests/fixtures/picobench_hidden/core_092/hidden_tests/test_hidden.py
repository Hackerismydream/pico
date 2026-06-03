from checks import aggregate_checks


def test_missing_failure_category_becomes_unknown():
    assert aggregate_checks([{'passed': False}])['failure_category'] == 'unknown'
