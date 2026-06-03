from lineage import verify_resume_lineage


def test_valid_resume_lineage_passes():
    previous = {'run_id': 'r1', 'session_id': 's', 'checkpoints': ['c1']}
    resumed = {'parent_run_id': 'r1', 'session_id': 's', 'checkpoint_id': 'c1'}
    assert verify_resume_lineage(previous, resumed) is True
    assert verify_resume_lineage(previous, {'parent_run_id': 'wrong', 'session_id': 's', 'checkpoint_id': 'c1'}) is False
