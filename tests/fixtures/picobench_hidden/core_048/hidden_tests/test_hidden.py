from memory_select import select_memory_notes

def test_verified_tool_observation_kept():
    notes = [{'text': 'x', 'source': 'tool', 'verified': True}, {'text': 'y', 'source': 'tool'}]
    assert select_memory_notes(notes) == [{'text': 'x', 'source': 'tool', 'verified': True}]
