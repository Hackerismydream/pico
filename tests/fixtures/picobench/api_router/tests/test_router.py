from router import Router


def test_router_normalizes_trailing_slash():
    router = Router()
    handler = object()
    router.add("/users/", handler)
    assert router.get("/users") is handler
    assert router.get("/users/") is handler
