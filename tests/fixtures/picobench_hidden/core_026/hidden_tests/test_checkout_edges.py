import pytest
from src.catalog import Catalog
from src.checkout import checkout


def test_unknown_coupon_is_ignored_but_stock_is_reserved():
    catalog = Catalog({"pen": 5})
    assert checkout(catalog, {"pen": 3}, {"pen": 2}, coupon="NOPE")["total"] == 6
    assert catalog.available("pen") == 2


def test_unknown_sku_fails_before_reservation():
    catalog = Catalog({"pen": 1})
    with pytest.raises(ValueError):
        checkout(catalog, {"book": 1}, {"book": 9})
    assert catalog.available("pen") == 1
