from parser import parse_items
from renderer import render_items


def test_parser_preserves_order_after_cleanup():
    assert parse_items(" b, a, c ") == ["b", "a", "c"]


def test_renderer_returns_empty_string_for_empty_input():
    assert render_items(" , ") == ""
