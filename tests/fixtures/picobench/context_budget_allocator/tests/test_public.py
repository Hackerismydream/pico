from context_budget import allocate_sections


def test_required_sections_are_kept_before_optional_sections():
    sections = [
        {'name': 'prefix', 'tokens': 40, 'priority': 1, 'required': True},
        {'name': 'history', 'tokens': 70, 'priority': 9, 'required': False},
        {'name': 'memory', 'tokens': 30, 'priority': 5, 'required': False},
    ]
    assert allocate_sections(sections, budget=80) == ['prefix', 'memory']
