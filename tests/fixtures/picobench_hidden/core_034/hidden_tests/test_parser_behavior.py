from parser import parse_pair


def test_parser_strips_key_and_value():
    assert parse_pair(" name = pico ") == ("name", "pico")


def test_parser_keeps_equals_inside_value():
    assert parse_pair("token=a=b") == ("token", "a=b")
