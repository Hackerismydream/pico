from app import build_parser, main


def test_greeting_can_be_uppercase():
    assert main(["--uppercase", "pico"]) == "HELLO PICO"


def test_help_mentions_uppercase_flag():
    assert "--uppercase" in build_parser().format_help()
