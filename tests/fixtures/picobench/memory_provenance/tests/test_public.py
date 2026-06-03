from memory_select import select_memory_notes

def test_filters_unverified_model_notes():
    notes = [{'text': 'a', 'source': 'model'}, {'text': 'b', 'source': 'user'}]
    assert select_memory_notes(notes) == [{'text': 'b', 'source': 'user'}]


def test_keeps_only_verified_tool_notes():
    notes = [{'text': 'x', 'source': 'tool', 'verified': True}, {'text': 'y', 'source': 'tool'}]
    assert select_memory_notes(notes) == [{'text': 'x', 'source': 'tool', 'verified': True}]
