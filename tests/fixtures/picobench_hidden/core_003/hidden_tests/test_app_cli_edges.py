from app import main


def test_default_greeting_stays_lowercase():
    assert main(["pico"]) == "hello pico"


def test_uppercase_works_for_other_names():
    assert main(["--uppercase", "agent"]) == "HELLO AGENT"
