from table import render_table


def test_render_markdown_table():
    assert render_table(["Name", "Score"], [["Pico", 9]]) == "| Name | Score |\n|---|---|\n| Pico | 9 |"


def test_render_table_formats_none_as_empty_cell():
    assert "|  |" in render_table(["Name"], [[None]])
