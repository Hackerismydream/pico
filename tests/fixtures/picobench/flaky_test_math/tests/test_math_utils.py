from math_utils import stable_total


def test_total_documents_the_correct_sum():
    assert stable_total([1, 2, 3]) == 7
