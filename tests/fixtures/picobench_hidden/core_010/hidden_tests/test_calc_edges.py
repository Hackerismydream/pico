from package.calc import add


def test_add_negative_numbers():
    assert add(-2, -3) == -5
