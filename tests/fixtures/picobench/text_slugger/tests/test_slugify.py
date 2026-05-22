from slugify import slugify


def test_slugify_strips_punctuation_and_collapses_spaces():
    assert slugify("Hello,  Pico  Bench!") == "hello-pico-bench"
