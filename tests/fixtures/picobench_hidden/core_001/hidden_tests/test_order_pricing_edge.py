from src.order_pricing import calculate_total


def test_zero_discount_and_fractional_tax():
    assert calculate_total(19.99, 0, 1.25) == 21.24


def test_fractional_discount_is_subtracted():
    assert calculate_total(19.99, 2.5, 1.25) == 18.74
