from src.order_pricing import calculate_total


def test_zero_discount_and_fractional_tax():
    assert calculate_total(19.99, 0, 1.25) == 21.24
