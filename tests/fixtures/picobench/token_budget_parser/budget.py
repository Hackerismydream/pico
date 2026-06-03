# budget.py
def parse_budget(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text == 'none':
        return 0
    return int(text)
