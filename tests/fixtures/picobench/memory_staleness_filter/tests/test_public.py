from stale_memory import filter_fresh_memories


def test_drops_memory_when_file_fingerprint_changed():
    memories = [{'text': 'old', 'path': 'a.py', 'fingerprint': 'old'}, {'text': 'fresh', 'path': 'b.py', 'fingerprint': 'same'}]
    assert filter_fresh_memories(memories, {'a.py': 'new', 'b.py': 'same'}) == [memories[1]]
