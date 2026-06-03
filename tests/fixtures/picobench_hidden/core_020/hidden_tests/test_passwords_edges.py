from passwords import is_strong


def test_password_rejects_spaces_and_missing_digit():
    assert not is_strong("Pico Bench 2026")
    assert not is_strong("PicoBench")
