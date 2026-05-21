import pytest

from notes import read_note


def test_rejects_absolute_path(tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ValueError):
        read_note(root, str(outside))
