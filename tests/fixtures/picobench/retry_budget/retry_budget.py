# retry_budget.py
class RetryBudget:
    def __init__(self, limit): self.limit=limit
    def allow(self, code): return True
