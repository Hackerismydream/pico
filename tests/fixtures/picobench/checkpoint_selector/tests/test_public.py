from checkpoint import latest_checkpoint


def test_latest_valid_checkpoint_wins():
    checkpoints = [
        {'checkpoint_id': 'a', 'created_at': '2026-01-01T00:00:00Z', 'status': 'valid'},
        {'checkpoint_id': 'b', 'created_at': '2026-01-02T00:00:00Z', 'status': 'invalid'},
        {'checkpoint_id': 'c', 'created_at': '2026-01-03T00:00:00Z', 'status': 'valid'},
        {'checkpoint_id': 'd', 'created_at': '2026-01-04T00:00:00Z', 'status': 'invalid'},
    ]
    assert latest_checkpoint(checkpoints) == 'c'
