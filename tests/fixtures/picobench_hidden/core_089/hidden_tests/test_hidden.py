from checkpoint import latest_checkpoint


def test_returns_none_without_valid_checkpoint():
    assert latest_checkpoint([{'checkpoint_id': 'x', 'created_at': '2026-01-01T00:00:00Z', 'status': 'invalid'}]) is None
