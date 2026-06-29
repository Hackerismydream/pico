import json

from pico.run_store import RunStore
from pico.runtime_kernel import RuntimeEvent
from pico.task_state import STOP_REASON_FINAL_ANSWER_RETURNED, TaskState


def test_run_store_creates_run_directory_and_state_file(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    state = TaskState.create(run_id="run_001", task_id="task_001", user_request="Inspect the repo.")

    run_dir = store.start_run(state)

    assert run_dir == store.run_dir(state.run_id)
    assert run_dir.exists()
    persisted = json.loads((run_dir / "task_state.json").read_text(encoding="utf-8"))
    assert persisted["task_id"] == "task_001"
    assert persisted["run_id"] == "run_001"
    assert persisted["user_request"] == "Inspect the repo."


def test_run_store_appends_trace_jsonl(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    state = TaskState.create(run_id="run_002", task_id="task_002", user_request="Trace the run.")
    store.start_run(state)

    store.append_trace(state, {"event": "run_started", "created_at": "2026-04-07T00:00:00+00:00"})
    store.append_trace(
        state.run_id,
        {
            "event": "prompt_built",
            "created_at": "2026-04-07T00:00:01+00:00",
            "prompt_metadata": {"prompt_chars": 128, "secret_env_count": 1},
        },
    )
    store.append_trace(state.run_id, {"event": "run_finished", "created_at": "2026-04-07T00:00:02+00:00"})

    lines = (store.trace_path(state.run_id)).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["event"] == "run_started"
    assert json.loads(lines[1])["event"] == "prompt_built"
    assert json.loads(lines[2])["event"] == "run_finished"


def test_run_store_writes_report_json(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    state = TaskState.create(run_id="run_003", task_id="task_003", user_request="Report the run.")
    store.start_run(state)
    state.finish_success("Done.")

    store.write_task_state(state)
    store.write_report(state, {"task_state": state.to_dict(), "stop_reason": state.stop_reason})

    report = json.loads(store.report_path(state.run_id).read_text(encoding="utf-8"))
    assert report["stop_reason"] == STOP_REASON_FINAL_ANSWER_RETURNED
    assert report["task_state"]["final_answer"] == "Done."


def test_run_store_tolerates_missing_final_report(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    state = TaskState.create(run_id="run_004", task_id="task_004", user_request="Crash before finalize.")

    store.start_run(state)
    store.append_trace(state, {"event": "run_started"})

    assert store.trace_path(state.run_id).exists()
    assert not store.report_path(state.run_id).exists()


def test_run_store_writes_and_loads_runtime_event_ledger(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_005"}),
        RuntimeEvent(type="terminal_status", payload={"invocation_id": "run_005", "status": "completed"}),
    ]

    path = store.write_runtime_events("run_005", events)
    loaded = store.load_runtime_events("run_005")

    assert path == store.runtime_events_path("run_005")
    assert [event.type for event in loaded] == ["invocation_start", "terminal_status"]
    assert loaded[0].payload["invocation_id"] == "run_005"


def test_run_store_writes_headless_task_artifacts(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")

    facts_path = store.write_task_run_facts("taskrun_001", {"task_run_id": "taskrun_001"})
    wal_path = store.append_task_run_wal("taskrun_001", {"event": "task_run_started"})
    export_path = store.write_task_run_export("taskrun_001", {"status": "pass"})

    assert facts_path == store.task_run_facts_path("taskrun_001")
    assert wal_path == store.task_run_wal_path("taskrun_001")
    assert export_path == store.task_run_export_path("taskrun_001")
    assert json.loads(facts_path.read_text(encoding="utf-8"))["task_run_id"] == "taskrun_001"
    assert json.loads(wal_path.read_text(encoding="utf-8").strip())["event"] == "task_run_started"
    assert json.loads(export_path.read_text(encoding="utf-8"))["status"] == "pass"
