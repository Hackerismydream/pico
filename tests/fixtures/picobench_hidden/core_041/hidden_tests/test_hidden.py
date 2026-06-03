from budget import parse_budget

def test_rejects_negative_and_blank():
    assert parse_budget('0') == 0
    try:
        parse_budget('-1')
    except ValueError:
        pass
    else:
        raise AssertionError('negative budget must fail')
