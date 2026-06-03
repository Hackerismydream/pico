from parser import parse_document
from renderer import render_summary


def test_document_without_frontmatter_uses_first_body_line():
    assert render_summary("First line\nSecond") == "First line"


def test_empty_tags_are_ignored():
    doc = parse_document("---\ntitle: T\ntags: alpha, , beta\n---\nBody")
    assert doc["metadata"]["tags"] == ["alpha", "beta"]
