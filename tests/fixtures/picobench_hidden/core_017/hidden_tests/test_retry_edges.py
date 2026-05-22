import pytest
from retry import retry


def test_retry_reraises_last_error():
    with pytest.raises(RuntimeError):
        retry(lambda: (_ for _ in ()).throw(RuntimeError("boom")), attempts=2)
