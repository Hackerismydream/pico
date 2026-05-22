from router import Router


def test_router_keeps_root_path():
    router = Router()
    handler = object()
    router.add("/", handler)
    assert router.get("/") is handler
