from todo import parse_todos


def test_parse_todos_trims_spacing():
    assert parse_todos("  - [ ]   fix bug  ") == ["fix bug"]
