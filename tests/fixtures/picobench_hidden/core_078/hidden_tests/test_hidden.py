from policy_78 import normalize

def test_normalize_rejects_non_scalar():
    try:
        normalize(['allow'])
    except TypeError:
        pass
    else:
        raise AssertionError('lists must be rejected')
