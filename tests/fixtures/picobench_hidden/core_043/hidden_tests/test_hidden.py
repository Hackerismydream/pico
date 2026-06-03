from approvals import ApprovalLedger

def test_summary_counts_real_tools_while_ignoring_blank_tool_names():
    ledger = ApprovalLedger()
    ledger.record('', 'allow')
    ledger.record('run_shell', 'deny')
    ledger.record('run_shell', 'allow')
    assert ledger.summary() == {'run_shell': {'allow': 1, 'deny': 1}}
