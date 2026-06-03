from dedupe import dedupe_tool_calls


def test_removes_exact_duplicate_calls():
    calls = [{'name': 'read_file', 'args': {'path': 'a'}}, {'name': 'read_file', 'args': {'path': 'a'}}]
    assert dedupe_tool_calls(calls) == [calls[0]]
