from pathlib import Path


REQUIRED = ["report.json", "trace.jsonl", "task_state.json"]


def copy_bundle(run_dir, output_dir):
    run_dir = Path(run_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ["report.json", "trace.jsonl"]:
        target = output_dir / name
        target.write_text((run_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
        copied.append(name)
    return copied
