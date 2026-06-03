from lineage import verify_resume_lineage


def test_wrong_session_or_checkpoint_fails():
    previous = {'run_id': 'r1', 'session_id': 's', 'checkpoints': ['c1']}
    assert verify_resume_lineage(previous, {'parent_run_id': 'r1', 'session_id': 'other', 'checkpoint_id': 'c1'}) is False
    assert verify_resume_lineage(previous, {'parent_run_id': 'r1', 'session_id': 's', 'checkpoint_id': 'missing'}) is False
