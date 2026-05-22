import pytest
from metrics import Counter


def test_counter_rejects_negative_amount():
    with pytest.raises(ValueError):
        Counter().inc(-1)
