from prompt_cache import build_cache_key


def test_cache_key_ignores_run_id_and_created_at():
    sections = [{'name': 'prefix', 'content': 'A'}]
    a = build_cache_key('deepseek', sections, {'run_id': 'r1', 'created_at': 'now'})
    b = build_cache_key('deepseek', sections, {'run_id': 'r2', 'created_at': 'later'})
    assert a == b
