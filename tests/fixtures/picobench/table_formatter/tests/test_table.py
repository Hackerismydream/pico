from table import render_table


def test_render_markdown_table():
    assert render_table(["Name", "Score"], [["Pico", 9]]) == "| Name | Score |\n|---|---|\n| Pico | 9 |"
