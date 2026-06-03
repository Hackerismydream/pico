from secrets import secret_env_names


def test_detection_is_case_insensitive_and_skips_empty_values():
    env = {'db_password': 'p', 'EMPTY_SECRET': '', 'normal': '1'}
    assert secret_env_names(env) == ['db_password']
