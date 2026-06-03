from evidence import REQUIRED, copy_bundle
from manifest import build_manifest


def test_bundle_copies_all_required_files(tmp_path):
    run_dir = tmp_path / "run"
    out_dir = tmp_path / "out"
    run_dir.mkdir()
    for name in REQUIRED:
        (run_dir / name).write_text(name, encoding="utf-8")
    copied = copy_bundle(run_dir, out_dir)
    assert sorted(copied) == sorted(REQUIRED)
    assert build_manifest(copied)["files"] == sorted(REQUIRED)
