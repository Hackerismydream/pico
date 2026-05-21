import csv


def import_inventory(path):
    items = {}
    with open(path, newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            items[row["sku"]] = int(row["qty"])
    return items
