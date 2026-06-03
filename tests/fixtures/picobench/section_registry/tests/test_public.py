from sections import *

def test_public_behavior():
    sections = [{'name': 'history', 'priority': 20}, {'name': 'prefix', 'priority': 1}]
    assert render_sections(sections) == ['prefix', 'history']

def test_expired_sections_are_skipped():
    assert render_sections([{'name': 'old', 'priority': 1, 'expired': True}]) == []
