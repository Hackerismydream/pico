from rules import compile_repo_rules

def test_trims_deny_write_paths_and_ignores_comments():
    text = '# deny_write: no\n- deny_write:  src/secrets/  \n\n- allow: tests'
    assert compile_repo_rules(text)['deny_write'] == ['src/secrets/']
