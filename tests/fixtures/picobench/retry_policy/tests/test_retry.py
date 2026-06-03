from retry import retry


def test_retry_until_success():
    calls = {"count": 0}
    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ValueError("not yet")
        return "ok"
    assert retry(flaky, attempts=3) == "ok"
    assert calls["count"] == 3
