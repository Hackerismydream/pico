from metrics import Counter


def test_counter_inc_accepts_amount():
    counter = Counter()
    assert counter.inc(3) == 3
    assert counter.inc() == 4
