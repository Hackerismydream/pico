import pytest
from retry import retry


def test_retry_reraises_last_error():
    with pytest.raises(RuntimeError):
        retry(lambda: (_ for _ in ()).throw(RuntimeError("boom")), attempts=2)


def test_retry_uses_all_attempts_before_reraising():
    calls = {"count": 0}

    def always_fails():
        calls["count"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        retry(always_fails, attempts=2)
    assert calls["count"] == 2
