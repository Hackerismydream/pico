from checkpoint import save_checkpoint
from resume import resume_state


def test_resume_preserves_existing_state(tmp_path):
    path = tmp_path / "state.json"
    save_checkpoint(path, {"task": "bench", "notes": ["read files"]})
    assert resume_state(path, "run tests") == {
        "task": "bench",
        "notes": ["read files"],
        "step": "run tests",
        "resumed": True,
    }
