from replay import *

def test_hidden_behavior():
    assert 'PATH=/bin' in replay_command('pytest', {'PATH': '/bin'})
