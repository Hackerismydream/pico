from budget import parse_budget

def test_parse_k_suffix_and_none():
    assert parse_budget('8k') == 8000
    assert parse_budget(' none ') is None

def test_rejects_negative_budget():
    try:
        parse_budget('-1')
    except ValueError:
        pass
    else:
        raise AssertionError('negative budget must fail')
