from sandbox_paths import sanitize_path


def test_normalizes_safe_relative_path():
    assert sanitize_path('./src/../src/app.py') == 'src/app.py'
