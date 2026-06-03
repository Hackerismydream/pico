from schema_diff import *

def test_hidden_behavior():
    assert diff_schema({}, {'b': 'int', 'a': 'str'})['added'] == ['a', 'b']
