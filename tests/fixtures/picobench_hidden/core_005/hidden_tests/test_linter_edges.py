from linter import lint_markdown


def test_clean_multiline_document_has_no_errors():
    assert lint_markdown("# Title\n\nbody\n") == []
