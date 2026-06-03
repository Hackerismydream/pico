from package.calc import add
import tomllib
from pathlib import Path


def test_add_negative_numbers():
    assert add(-2, -3) == -5


def test_pytest_config_uses_existing_tests_directory():
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
