import time
from cache import TTLCache


def test_expired_item_is_removed(monkeypatch):
    now = [1.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    cache = TTLCache()
    cache.set("k", "v", ttl=1)
    now[0] = 3.0
    assert cache.get("k") is None
    assert cache._items == {}
