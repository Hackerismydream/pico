from reporter import summarize_amounts


def test_summarize_amounts_ignores_negative_and_blank_values():
    assert summarize_amounts([{"amount": ""}, {"amount": "-3"}, {"amount": "7"}]) == 7
