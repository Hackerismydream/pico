from manifest_merge import merge_manifest_update

def test_status_update_preserves_identity():
    base = {'run_id': 'r1', 'task_id': 't1', 'provider': 'deepseek', 'status': 'running'}
    merged = merge_manifest_update(base, {'status': 'completed', 'stop_reason': 'final_answer_returned'})
    assert merged['run_id'] == 'r1'
    assert merged['provider'] == 'deepseek'
    assert merged['status'] == 'completed'

def test_nested_paths_are_merged_without_dropping_existing_entries():
    base = {'paths': {'trace': 'trace.jsonl'}}
    merged = merge_manifest_update(base, {'paths': {'report': 'report.json'}})
    assert merged['paths'] == {'trace': 'trace.jsonl', 'report': 'report.json'}
