import tomllib
from pathlib import Path


def test_pytest_testpaths_points_to_tests_directory():
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
