from .discounts import apply_coupon


def checkout(catalog, items, prices, coupon=None):
    subtotal = sum(prices[sku] * quantity for sku, quantity in items.items())
    return {"total": subtotal, "reserved": dict(items)}
