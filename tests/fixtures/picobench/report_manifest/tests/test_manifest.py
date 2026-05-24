from manifest import build_manifest


def test_manifest_includes_report_and_status():
    manifest = build_manifest("smoke", [{"passed": True}, {"passed": False}])
    assert manifest["report"]["passed"] == 1
    assert manifest["status"] == "failed"


def test_manifest_lists_summary_fields():
    manifest = build_manifest("smoke", [{"passed": True}])
    assert manifest["summary"] == "1/1 checks passed"
