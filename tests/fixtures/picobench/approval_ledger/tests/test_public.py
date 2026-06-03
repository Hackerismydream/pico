from approvals import ApprovalLedger

def test_summary_counts_by_tool_and_decision():
    ledger = ApprovalLedger()
    ledger.record('write_file', 'allow')
    ledger.record('write_file', 'deny', 'scope')
    assert ledger.summary()['write_file'] == {'allow': 1, 'deny': 1}

def test_summary_ignores_blank_tool_names():
    ledger = ApprovalLedger()
    ledger.record('', 'allow')
    ledger.record('run_shell', 'deny')
    assert ledger.summary() == {'run_shell': {'deny': 1}}
