def build_report(name, checks):
    passed = sum(1 for check in checks if check["passed"])
    return {
        "name": name,
        "passed": passed,
        "total": len(checks),
    }
