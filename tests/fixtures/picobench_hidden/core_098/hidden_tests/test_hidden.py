from stale_memory import filter_fresh_memories


def test_path_memory_without_current_fingerprint_is_dropped():
    memory = {'text': 'old', 'path': 'missing.py', 'fingerprint': 'abc'}
    assert filter_fresh_memories([memory], {}) == []
