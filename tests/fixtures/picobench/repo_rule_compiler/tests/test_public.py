from rules import compile_repo_rules

def test_extracts_deny_write_paths():
    text = '- deny_write: secrets/\n- deny_write: .env'
    assert compile_repo_rules(text)['deny_write'] == ['secrets/', '.env']
