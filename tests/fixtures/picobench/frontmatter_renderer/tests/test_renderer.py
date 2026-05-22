from parser import parse_document
from renderer import render_summary


def test_parse_frontmatter_and_render_summary():
    text = "---\ntitle: Launch Plan\ntags: release, pico\n---\nBody starts here."
    doc = parse_document(text)
    assert doc["metadata"] == {"title": "Launch Plan", "tags": ["release", "pico"]}
    assert doc["body"] == "Body starts here."
    assert render_summary(text) == "Launch Plan [release, pico]"
