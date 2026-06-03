from sandbox_paths import sanitize_path


def test_rejects_absolute_and_parent_paths():
    for path in ['/tmp/x', '../x', '~/secret']:
        try:
            sanitize_path(path)
        except ValueError:
            pass
        else:
            raise AssertionError(f'{path} should fail')
