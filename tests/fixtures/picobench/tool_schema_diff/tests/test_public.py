from schema_diff import *

def test_public_behavior():
    assert diff_schema({'path': 'str', 'content': 'str'}, {'path': 'str'})['removed'] == ['content']
    assert diff_schema({}, {'b': 'int', 'a': 'str'})['added'] == ['a', 'b']
