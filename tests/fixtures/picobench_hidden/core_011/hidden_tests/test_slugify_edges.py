from slugify import slugify


def test_slugify_handles_tabs_and_edges():
    assert slugify("  Agent\tRuntime!!! ") == "agent-runtime"
