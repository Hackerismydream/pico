from parser import parse_items
from renderer import render_items


def test_parser_drops_blank_items_and_trims_values():
    assert parse_items(" alpha, , beta ") == ["alpha", "beta"]


def test_renderer_uses_existing_parser_contract():
    assert render_items("alpha,beta") == "- alpha\n- beta"
