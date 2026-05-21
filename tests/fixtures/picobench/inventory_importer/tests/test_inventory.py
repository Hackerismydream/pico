from inventory import import_inventory


def test_bad_rows_are_skipped(tmp_path):
    csv_path = tmp_path / "inventory.csv"
    csv_path.write_text("sku,qty\nA1,3\n,9\nB2,bad\nC3,-1\nD4,4\n", encoding="utf-8")

    assert import_inventory(csv_path) == {"A1": 3, "D4": 4}
