from parser import parse_document
from renderer import render_summary


def test_parse_frontmatter_and_render_summary():
    text = "---\ntitle: Launch Plan\ntags: release, pico\n---\nBody starts here."
    doc = parse_document(text)
    assert doc["metadata"] == {"title": "Launch Plan", "tags": ["release", "pico"]}
    assert doc["body"] == "Body starts here."
    assert render_summary(text) == "Launch Plan [release, pico]"


def test_empty_tags_are_ignored():
    doc = parse_document("---\ntitle: T\ntags: alpha, , beta\n---\nBody")
    assert doc["metadata"]["tags"] == ["alpha", "beta"]


def test_summary_without_frontmatter_uses_first_body_line():
    assert render_summary("First line\nSecond") == "First line"
