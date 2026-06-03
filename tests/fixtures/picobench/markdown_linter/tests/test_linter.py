import linter
from linter import has_errors, lint_markdown


def test_lints_trailing_space_and_bad_heading():
    assert lint_markdown("#Bad\nok \n") == [
        (1, "bad-heading"),
        (2, "trailing-space"),
    ]


def test_has_errors_wraps_lint_markdown():
    assert has_errors("#Bad") is True
    assert has_errors("# Good") is False


def test_rules_are_split_into_named_helpers():
    assert callable(getattr(linter, "check_trailing_space", None))
    assert callable(getattr(linter, "check_heading", None))
