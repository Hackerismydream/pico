from passwords import is_strong


def test_password_requires_mixed_classes():
    assert is_strong("Pico2026")
    assert not is_strong("picobench")
    assert not is_strong("PICOONLY")
    assert not is_strong("Short1")
