import pytest

from notes import read_note


def test_rejects_path_traversal(tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    (root / "safe.txt").write_text("safe", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError):
        read_note(root, "../secret.txt")


def test_reads_safe_note(tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    (root / "safe.txt").write_text("safe", encoding="utf-8")

    assert read_note(root, "safe.txt") == "safe"
