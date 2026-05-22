from filterer import filter_records


def test_filter_records_by_numeric_minimum():
    rows = [{"score": 3}, {"score": 9}, {"score": "bad"}, {"name": "missing"}]
    assert filter_records(rows, "score", 5) == [{"score": 9}]
