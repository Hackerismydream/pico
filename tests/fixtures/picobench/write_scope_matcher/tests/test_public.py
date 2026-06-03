from scope import allowed_write


def test_allows_children_inside_scope_only():
    assert allowed_write('src/app.py', ['src']) is True
    assert allowed_write('docs/readme.md', ['src']) is False
    assert allowed_write('src_backup/app.py', ['src']) is False
