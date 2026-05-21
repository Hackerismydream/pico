from inventory import import_inventory


def test_empty_file_returns_empty_mapping(tmp_path):
    csv_path = tmp_path / "inventory.csv"
    csv_path.write_text("sku,qty\n", encoding="utf-8")

    assert import_inventory(csv_path) == {}
