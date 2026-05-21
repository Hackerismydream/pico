from src.order_pricing import calculate_total


def test_discount_is_subtracted_before_tax_is_added():
    assert calculate_total(100, 15, 8.5) == 93.5
