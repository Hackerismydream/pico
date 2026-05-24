from evidence import REQUIRED, copy_bundle


def test_bundle_preserves_file_contents(tmp_path):
    run_dir = tmp_path / "run"
    out_dir = tmp_path / "out"
    run_dir.mkdir()
    for name in REQUIRED:
        (run_dir / name).write_text(f"content:{name}", encoding="utf-8")
    copy_bundle(run_dir, out_dir)
    assert (out_dir / "task_state.json").read_text(encoding="utf-8") == "content:task_state.json"
