from table import render_table


def test_render_table_escapes_none_as_empty():
    assert "|  |" in render_table(["Name"], [[None]])
