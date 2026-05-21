from app import main


def test_default_greeting_stays_lowercase():
    assert main(["pico"]) == "hello pico"
