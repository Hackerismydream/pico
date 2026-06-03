# approvals.py
class ApprovalLedger:
    def __init__(self):
        self.items = []

    def record(self, tool, decision, reason=''):
        self.items.append({'tool': tool, 'decision': decision, 'reason': reason})

    def summary(self):
        return {}
