import json
from pathlib import Path


def save_checkpoint(path, state):
    Path(path).write_text(json.dumps(state), encoding="utf-8")


def load_checkpoint(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
