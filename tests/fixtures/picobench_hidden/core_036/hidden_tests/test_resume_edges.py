from checkpoint import save_checkpoint
from resume import resume_state


def test_resume_does_not_alias_loaded_state(tmp_path):
    path = tmp_path / "state.json"
    original = {"task": "bench", "notes": []}
    save_checkpoint(path, original)
    resumed = resume_state(path, "verify")
    resumed["notes"].append("changed")
    assert resume_state(path, "verify")["notes"] == []


def test_resume_keeps_unknown_fields(tmp_path):
    path = tmp_path / "state.json"
    save_checkpoint(path, {"task": "bench", "checkpoint_id": "abc"})
    assert resume_state(path, "continue")["checkpoint_id"] == "abc"
