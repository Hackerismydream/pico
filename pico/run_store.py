"""运行工件落盘。

session.json 负责保存“可恢复的会话状态”；RunStore 负责保存“单次运行的审计工件”，
例如 task_state、trace 和 report。两者分开后，恢复现场和复盘证据不会混在一起。
"""

import json
import re
import tempfile
from pathlib import Path

from .runtime_kernel import runtime_event_from_dict, runtime_event_to_dict
from .security import redact_artifact

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _run_id(value):
    if hasattr(value, "run_id"):
        value = value.run_id
    run_id = str(value)
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"invalid run id: {run_id}")
    return run_id


class RunStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id):
        return self.root / _run_id(run_id)

    def task_state_path(self, run_id):
        return self.run_dir(run_id) / "task_state.json"

    def trace_path(self, run_id):
        return self.run_dir(run_id) / "trace.jsonl"

    def report_path(self, run_id):
        return self.run_dir(run_id) / "report.json"

    def runtime_events_path(self, run_id):
        return self.run_dir(run_id) / "runtime_events.jsonl"

    def task_run_facts_path(self, run_id):
        return self.run_dir(run_id) / "task_run.json"

    def task_run_wal_path(self, run_id):
        return self.run_dir(run_id) / "task_run_wal.jsonl"

    def task_run_export_path(self, run_id):
        return self.run_dir(run_id) / "task_run_export.json"

    def eval_grid_export_path(self, run_id):
        return self.run_dir(run_id) / "eval_grid_export.json"

    def eval_grid_report_path(self, run_id):
        return self.run_dir(run_id) / "eval_grid_report.md"

    def start_run(self, task_state):
        # 每次 ask() 都会生成一个 run 目录。
        # 这样一次用户请求对应一组独立工件，后续排查更容易。
        run_dir = self.run_dir(task_state)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.write_task_state(task_state)
        return run_dir

    def write_task_state(self, task_state):
        path = self.task_state_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, task_state.to_dict())
        return path

    def append_trace(self, task_state, event):
        path = self.trace_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        # trace 采用 jsonl 追加写入，原因是 agent 运行过程是流式事件序列，
        # 逐条落盘比“最后一次性写整份 trace”更稳，也更适合调试。
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
        return path

    def write_trace(self, run_id, events):
        path = self.trace_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(event, sort_keys=True, ensure_ascii=True) for event in events]
        self._write_text_atomic(path, "\n".join(lines) + ("\n" if lines else ""))
        return path

    def write_report(self, task_state, report):
        path = self.report_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, report)
        return path

    def write_runtime_events(self, run_id, events, *, secret_env_names=None):
        path = self.runtime_events_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(
                redact_artifact(runtime_event_to_dict(event), secret_env_names=secret_env_names),
                sort_keys=True,
                ensure_ascii=True,
            )
            for event in events
        ]
        self._write_text_atomic(path, "\n".join(lines) + ("\n" if lines else ""))
        return path

    def write_task_run_facts(self, run_id, payload):
        path = self.task_run_facts_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, payload)
        return path

    def append_task_run_wal(self, run_id, event):
        path = self.task_run_wal_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
        return path

    def write_task_run_export(self, run_id, payload):
        path = self.task_run_export_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, payload)
        return path

    def write_eval_grid_export(self, run_id, payload):
        path = self.eval_grid_export_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, payload)
        return path

    def write_eval_grid_report(self, run_id, text):
        path = self.eval_grid_report_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_text_atomic(path, text)
        return path

    def load_task_state(self, task_id):
        return json.loads(self.task_state_path(task_id).read_text(encoding="utf-8"))

    def load_report(self, task_id):
        return json.loads(self.report_path(task_id).read_text(encoding="utf-8"))

    def load_runtime_events(self, run_id):
        path = self.runtime_events_path(run_id)
        return [
            runtime_event_from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _write_json_atomic(self, path, payload):
        # 原子写：先写临时文件，再 replace。
        # 这样即使中途异常，也不容易留下半截 JSON。
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(path)

    def _write_text_atomic(self, path, text):
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
        ) as handle:
            handle.write(text)
            temp_name = handle.name
        Path(temp_name).replace(path)
