from filterer import filter_records


def test_filter_records_accepts_numeric_strings():
    assert filter_records([{"score": "7"}, {"score": "4"}], "score", 5) == [{"score": "7"}]
