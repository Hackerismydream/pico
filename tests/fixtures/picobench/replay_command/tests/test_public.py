from replay import *

def test_public_behavior():
    text = replay_command('pytest', {'DEEPSEEK_API_KEY': 'secret', 'PATH': '/bin'})
    assert 'secret' not in text
    assert '<redacted>' in text
    assert 'PATH=/bin' in text
