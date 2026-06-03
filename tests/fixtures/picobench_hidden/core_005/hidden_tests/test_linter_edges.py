import linter
from linter import lint_markdown


def test_clean_multiline_document_has_no_errors():
    assert lint_markdown("# Title\n\nbody\n") == []


def test_refactor_keeps_rule_helpers_available():
    assert callable(getattr(linter, "check_trailing_space", None))
    assert callable(getattr(linter, "check_heading", None))
