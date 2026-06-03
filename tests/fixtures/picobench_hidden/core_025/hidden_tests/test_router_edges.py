from router import Router


def test_router_keeps_root_path():
    router = Router()
    handler = object()
    router.add("/", handler)
    assert router.get("/") is handler


def test_trailing_slash_normalizes_when_route_added_without_slash():
    router = Router()
    handler = object()
    router.add("/projects", handler)
    assert router.get("/projects/") is handler
