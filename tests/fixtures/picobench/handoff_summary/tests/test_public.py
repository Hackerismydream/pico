from handoff import *

def test_public_behavior():
    result = build_handoff('fix parser', ['no env'], ['parser.py'])
    assert result['constraints'] == ['no env']
    assert result['changed_paths'] == ['parser.py']
