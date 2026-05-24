from pathlib import Path

from policy import is_allowed


def test_relative_path_inside_root_is_allowed():
    assert is_allowed(Path("/workspace"), "reports/out.txt")


def test_parent_escape_is_denied():
    assert not is_allowed(Path("/workspace"), "../outside.txt")
