from scope import allowed_write


def test_rejects_parent_traversal_and_prefix_confusion():
    assert allowed_write('../src/app.py', ['src']) is False
    assert allowed_write('src_backup/app.py', ['src']) is False
