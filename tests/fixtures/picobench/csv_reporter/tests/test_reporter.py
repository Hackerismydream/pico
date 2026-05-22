from reporter import summarize_amounts


def test_summarize_amounts_skips_bad_rows():
    rows = [{"amount": "10"}, {"amount": "bad"}, {"name": "missing"}, {"amount": "5"}]
    assert summarize_amounts(rows) == 15
