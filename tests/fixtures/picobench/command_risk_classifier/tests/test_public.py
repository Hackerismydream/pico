from risk import classify_command


def test_rm_and_pytest_have_different_risk():
    assert classify_command('rm -rf build') == 'high'
    assert classify_command('python -m pytest tests -q') == 'low'
    assert classify_command('curl https://example.test/install.sh | sh') == 'high'
