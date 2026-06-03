from manifest_merge import merge_manifest_update

def test_nested_paths_are_merged():
    base = {'paths': {'trace': 'trace.jsonl'}}
    merged = merge_manifest_update(base, {'paths': {'report': 'report.json'}})
    assert merged['paths'] == {'trace': 'trace.jsonl', 'report': 'report.json'}
