from todo import parse_todos


def test_parse_open_todos_only():
    text = "- [ ] write tests\n- [x] done\nplain note\n- [ ] ship"
    assert parse_todos(text) == ["write tests", "ship"]


def test_parse_todos_trims_spacing():
    assert parse_todos("  - [ ]   fix bug  ") == ["fix bug"]
