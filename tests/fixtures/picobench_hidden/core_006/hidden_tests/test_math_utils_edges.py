from math_utils import stable_total


def test_empty_total_is_zero():
    assert stable_total([]) == 0
