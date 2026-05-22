import time


class TTLCache:
    def __init__(self):
        self._items = {}

    def set(self, key, value, ttl):
        self._items[key] = (value, time.time() + ttl)

    def get(self, key):
        item = self._items.get(key)
        return None if item is None else item[0]
