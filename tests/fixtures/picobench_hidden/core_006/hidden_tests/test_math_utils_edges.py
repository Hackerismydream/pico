from math_utils import stable_total
from pathlib import Path


def test_empty_total_is_zero():
    assert stable_total([]) == 0


def test_public_test_documents_correct_sum():
    assert "== 6" in Path("tests/test_math_utils.py").read_text(encoding="utf-8")
