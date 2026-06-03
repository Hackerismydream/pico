from pathlib import Path

from paths import normalize_path
from policy import is_allowed


def test_prefix_sibling_is_not_allowed():
    assert not is_allowed(Path("/tmp/work"), "../work-evil/file.txt")


def test_normalized_path_resolves_dot_segments():
    assert normalize_path(Path("/tmp/work"), "a/../b.txt") == Path("/tmp/work/b.txt")
