class Catalog:
    def __init__(self, stock):
        self.stock = dict(stock)

    def available(self, sku):
        return self.stock.get(sku, 0)

    def reserve(self, sku, quantity):
        self.stock[sku] = self.available(sku) - quantity
