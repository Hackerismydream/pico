from pathlib import Path

from tool import build_parser


def test_readme_mentions_real_subcommand():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "tool hello NAME" in readme


def test_help_mentions_hello():
    assert "hello" in build_parser().format_help()
