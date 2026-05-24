from parser import parse_pair


def test_parse_pair_preserves_outer_whitespace():
    assert parse_pair(" name = pico ") == (" name ", " pico ")
