from manifest import build_manifest


def test_all_passed_status_is_passed():
    manifest = build_manifest("release", [{"passed": True}, {"passed": True}])
    assert manifest["status"] == "passed"
    assert manifest["summary"] == "2/2 checks passed"


def test_empty_check_list_is_failed_and_explicit():
    manifest = build_manifest("empty", [])
    assert manifest["status"] == "failed"
    assert manifest["summary"] == "0/0 checks passed"
