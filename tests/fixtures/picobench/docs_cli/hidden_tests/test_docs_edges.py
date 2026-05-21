from pathlib import Path


def test_readme_no_longer_mentions_removed_greet_command():
    assert "tool greet NAME" not in Path("README.md").read_text(encoding="utf-8")
