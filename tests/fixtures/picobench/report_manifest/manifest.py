from report import build_report


def build_manifest(name, checks):
    report = build_report(name, checks)
    return {
        "schema_version": 1,
        "report": report,
    }
