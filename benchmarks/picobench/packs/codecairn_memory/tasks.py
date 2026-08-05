from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from .models import CodeCairnMemoryTask

_SCHEMA = "pico.picobench.codecairn-memory-tasks.v1"
_EXPECTED_COUNTS = {
    "calibration": 2,
    "formal": 8,
}


@lru_cache(maxsize=2)
def load_codecairn_memory_tasks(
    definition_kind: Literal["formal", "calibration"],
) -> tuple[CodeCairnMemoryTask, ...]:
    path = Path(__file__).resolve().parents[2] / "tasks" / "codecairn_memory" / f"{definition_kind}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != _SCHEMA:
        raise ValueError(f"unsupported CodeCairn Memory task schema: {path}")
    rows = payload.get("tasks")
    if not isinstance(rows, list):
        raise ValueError(f"CodeCairn Memory tasks must be a list: {path}")
    tasks = tuple(CodeCairnMemoryTask(**row) for row in rows)
    if len(tasks) != _EXPECTED_COUNTS[definition_kind]:
        raise ValueError(f"unexpected CodeCairn Memory task count: {path}")
    task_ids = tuple(task.task_id for task in tasks)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError(f"duplicate CodeCairn Memory task id: {path}")
    return tasks


__all__ = ["load_codecairn_memory_tasks"]
