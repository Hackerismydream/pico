import pytest
from src.catalog import Catalog
from src.checkout import checkout


def test_checkout_applies_coupon_and_reserves_stock():
    catalog = Catalog({"book": 3})
    result = checkout(catalog, {"book": 2}, {"book": 10}, coupon="SAVE10")
    assert result == {"total": 18.0, "reserved": {"book": 2}}
    assert catalog.available("book") == 1


def test_checkout_rejects_insufficient_stock():
    with pytest.raises(ValueError):
        checkout(Catalog({"book": 1}), {"book": 2}, {"book": 10})
