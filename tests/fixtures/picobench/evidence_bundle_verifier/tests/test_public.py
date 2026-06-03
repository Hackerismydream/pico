from bundle import verify_bundle

def test_requires_core_evidence_files():
    files = {'summary.json', 'run_manifest.json', 'provider_config_redacted.json', 'trace.jsonl'}
    assert verify_bundle(files) is True
    assert verify_bundle({'summary.json'}) is False
