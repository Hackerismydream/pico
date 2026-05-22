import time
from cache import TTLCache


def test_cache_expires_items(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    cache = TTLCache()
    cache.set("token", "abc", ttl=5)
    assert cache.get("token") == "abc"
    now[0] = 106.0
    assert cache.get("token") is None
