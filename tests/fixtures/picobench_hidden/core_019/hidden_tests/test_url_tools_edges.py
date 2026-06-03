from url_tools import join_url


def test_join_url_handles_empty_path():
    assert join_url("https://api.example.com/", "") == "https://api.example.com"
