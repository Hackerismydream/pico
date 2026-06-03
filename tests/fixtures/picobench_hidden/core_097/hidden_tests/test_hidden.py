from dedupe import dedupe_tool_calls


def test_args_order_does_not_affect_identity():
    calls = [{'name': 'x', 'args': {'a': 1, 'b': 2}}, {'name': 'x', 'args': {'b': 2, 'a': 1}}]
    assert dedupe_tool_calls(calls) == [calls[0]]
