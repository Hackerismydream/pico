from prompt_cache import build_cache_key


def test_cache_key_is_stable_across_section_order():
    a = build_cache_key('m', [{'name': 'b', 'content': '2'}, {'name': 'a', 'content': '1'}])
    b = build_cache_key('m', [{'name': 'a', 'content': '1'}, {'name': 'b', 'content': '2'}])
    assert a == b
