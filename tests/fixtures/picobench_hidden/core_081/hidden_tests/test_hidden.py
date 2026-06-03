from context_budget import allocate_sections


def test_optional_sections_are_sorted_by_priority_and_budgeted():
    sections = [
        {'name': 'low', 'tokens': 10, 'priority': 1, 'required': False},
        {'name': 'high', 'tokens': 10, 'priority': 10, 'required': False},
        {'name': 'mid', 'tokens': 10, 'priority': 5, 'required': False},
    ]
    assert allocate_sections(sections, budget=20) == ['high', 'mid']
