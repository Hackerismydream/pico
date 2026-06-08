import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from ..core.workspace import WorkspaceContext, now
from . import memory as memorylib
from .dream_lint import lint_memory_candidate
from .dream_report import write_dream_diff, write_dream_report
from .dream_store import (
    DREAM_DIR_NAME,
    DreamLock,
    DreamLockHeld,
    _dedupe_preserve_order,
    apply_candidate_payload,
    copy_memory_tree,
    dream_runs_dir,
    dream_snapshots_dir,
    ensure_memory_dir,
    load_dream_state,
    load_dream_task,
    official_payload_hashes,
    write_dream_state,
    write_dream_task,
)

APPLICABLE_DREAM_STATUSES = {"completed_candidate", "completed_with_warnings"}


def _new_dream_task_id(trigger="manual"):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    suffix = hashlib.sha1(f"{stamp}-{os.getpid()}-{trigger}".encode("utf-8")).hexdigest()[:6]
    return f"dream_{stamp}_{suffix}"


def dream_status_text(agent):
    state = load_dream_state(agent.memory_dir)
    task_id = state.get("last_task_id", "")
    if not task_id:
        return "No dream tasks yet."
    task = load_dream_task(agent.memory_dir, task_id)
    if not task:
        return f"Last dream task: {task_id}\nstatus: missing task file"
    return "\n".join(
        [
            f"dream: {task_id}",
            f"status: {task.get('status', 'unknown')}",
            f"lint: {task.get('lint_status', 'unknown')}",
            f"candidate: {task.get('candidate_store', '')}",
        ]
    )


def apply_dream_task(agent, task_id):
    try:
        with DreamLock(agent.memory_dir).acquire(purpose="apply", task_id=task_id):
            return _apply_dream_task_locked(agent, task_id)
    except DreamLockHeld as exc:
        raise memorylib.DreamApplyError("Dream already running.") from exc


def _apply_dream_task_locked(agent, task_id):
    task = load_dream_task(agent.memory_dir, task_id)
    if not task:
        raise memorylib.DreamApplyError(f"dream task not found: {task_id}")
    if task.get("status") == "applied":
        return f"Dream task already applied: {task_id}"
    if task.get("status") not in APPLICABLE_DREAM_STATUSES:
        raise memorylib.DreamApplyError(f"dream task cannot be applied with status: {task.get('status', 'unknown')}")
    candidate = Path(task["candidate_store"])
    if not candidate.exists():
        raise memorylib.DreamApplyError(f"dream candidate missing: {candidate}")

    lint_result = lint_memory_candidate(candidate)
    changed_files = write_dream_diff(Path(task.get("input_snapshot", "")), candidate, Path(task["diff_path"]))
    Path(task["lint_path"]).write_text(json.dumps(lint_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    task.update(
        {
            "changed_files": changed_files,
            "lint_status": lint_result["status"],
            "lint_errors": lint_result.get("errors", []),
            "lint_warnings": lint_result.get("warnings", []),
        }
    )
    if lint_result["status"] == "failed":
        task["status"] = "lint_failed"
        write_dream_task(agent.memory_dir, task)
        raise memorylib.DreamApplyError(f"dream task cannot be applied with lint status: {lint_result['status']}")

    base_files = task.get("base_files", {})
    current_files = official_payload_hashes(agent.memory_dir)
    if base_files != current_files:
        write_dream_task(agent.memory_dir, task)
        raise memorylib.DreamApplyError("official memory changed since candidate was created; rerun /dream")

    snapshot_id = f"snapshot_{datetime.now().strftime('%Y%m%d-%H%M%S')}_{task_id}"
    snapshot_path = dream_snapshots_dir(agent.memory_dir) / snapshot_id
    copy_memory_tree(agent.memory_dir, snapshot_path)
    apply_candidate_payload(candidate, agent.memory_dir)
    state = load_dream_state(agent.memory_dir)
    applied_at = now()
    processed = _dedupe_preserve_order([*state.get("processed_session_ids", []), *task.get("input_sessions", [])])
    pending = [session_id for session_id in state.get("pending_session_ids", []) if session_id not in set(processed)]
    state.update(
        {
            "processed_session_ids": processed,
            "pending_session_ids": pending,
            "last_apply_at": applied_at,
            "last_success_at": applied_at,
            "last_task_id": task_id,
        }
    )
    write_dream_state(agent.memory_dir, state)
    task.update({"status": "applied", "applied_at": applied_at, "snapshot_id": snapshot_id, "snapshot_path": str(snapshot_path)})
    write_dream_task(agent.memory_dir, task)
    agent.memory.state = memorylib.normalize_memory_state(agent.memory.state, agent.root)
    agent.session["memory"] = agent.memory.to_dict()
    return f"Applied dream task {task_id}.\nsnapshot: {snapshot_id}"


def discard_dream_task(agent, task_id):
    task = load_dream_task(agent.memory_dir, task_id)
    if not task:
        return f"error: dream task not found: {task_id}"
    if task.get("status") == "applied":
        return f"error: dream task already applied: {task_id}"
    task["status"] = "discarded"
    task["discarded_at"] = now()
    write_dream_task(agent.memory_dir, task)
    return f"Discarded dream task {task_id}."


def run_dream(agent, quiet=False, session_ids=None, trigger="manual", raise_on_lock=False, scan_cutoff=None):
    try:
        with DreamLock(agent.memory_dir).acquire(purpose="generate", task_id=""):
            return _run_dream_locked(
                agent,
                quiet=quiet,
                session_ids=session_ids,
                trigger=trigger,
                scan_cutoff=scan_cutoff,
            )
    except DreamLockHeld as exc:
        if raise_on_lock:
            raise memorylib.DreamLockHeld("dream already running") from exc
        return "Dream already running."


def _run_dream_locked(agent, quiet=False, session_ids=None, trigger="manual", scan_cutoff=None):
    from ..core.runtime import Pico

    ensure_memory_dir(agent.memory_dir)
    state = load_dream_state(agent.memory_dir)
    discovered = list(session_ids or [])
    processed = set(state.get("processed_session_ids", []))
    pending = _dedupe_preserve_order([*state.get("pending_session_ids", []), *discovered])
    pending = [session_id for session_id in pending if session_id not in processed]
    selected_session_ids = pending[: memorylib.DREAM_SESSION_CAP]
    scan_cutoff = float(scan_cutoff or datetime.now().timestamp())
    task_id = _new_dream_task_id(trigger=trigger)
    run_dir = dream_runs_dir(agent.memory_dir) / task_id
    input_snapshot = run_dir / "input-snapshot"
    candidate_store = run_dir / "candidate"
    diff_path = run_dir / "diff.patch"
    lint_path = run_dir / "lint.json"
    report_path = run_dir / "report.md"
    task = {
        "id": task_id,
        "trigger": trigger,
        "status": "running",
        "created_at": now(),
        "started_at": now(),
        "ended_at": "",
        "input_sessions": selected_session_ids,
        "input_snapshot": str(input_snapshot),
        "candidate_store": str(candidate_store),
        "diff_path": str(diff_path),
        "lint_path": str(lint_path),
        "report_path": str(report_path),
        "changed_files": [],
        "lint_status": "unknown",
        "lint_errors": [],
        "lint_warnings": [],
        "base_files": {},
        "scan_cutoff": scan_cutoff,
        "error": "",
    }
    write_dream_task(agent.memory_dir, task)
    try:
        base_files = official_payload_hashes(agent.memory_dir)
        copy_memory_tree(agent.memory_dir, input_snapshot)
        copy_memory_tree(agent.memory_dir, candidate_store)
        task["base_files"] = base_files
        write_dream_task(agent.memory_dir, task)
        dream_prompt = memorylib.build_dream_prompt(
            candidate_store,
            transcript_dir=str(agent.session_store.root),
            session_ids=selected_session_ids,
        )
        try:
            memory_scope = candidate_store.resolve().relative_to(agent.root)
        except ValueError:
            memory_scope = Path(".pico") / "memory" / DREAM_DIR_NAME / "runs" / task_id / "candidate"
        dream_agent = Pico(
            model_client=agent.model_client,
            workspace=WorkspaceContext.build(agent.root),
            session_store=agent.session_store,
            approval_policy="auto",
            max_steps=max(agent.max_steps, 20),
            max_new_tokens=max(agent.max_new_tokens, memorylib.DREAM_MIN_NEW_TOKENS),
            secret_env_names=agent.secret_env_names,
            feature_flags={**agent.feature_flags, "memory": False, "relevant_memory": False},
            write_scope=[str(memory_scope)],
            memory_dir=agent.memory_dir,
            auto_dream=False,
        )
        dream_agent.set_tool_profile("dream")
        dream_agent.refresh_prefix(force=True)
        result = dream_agent.ask(dream_prompt)
        changed_files = write_dream_diff(input_snapshot, candidate_store, diff_path)
        lint_result = lint_memory_candidate(candidate_store)
        lint_path.write_text(json.dumps(lint_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        task_status = "completed_candidate"
        if lint_result["status"] == "warning":
            task_status = "completed_with_warnings"
        elif lint_result["status"] == "failed":
            task_status = "lint_failed"
        task.update(
            {
                "status": task_status,
                "ended_at": now(),
                "changed_files": changed_files,
                "lint_status": lint_result["status"],
                "lint_errors": lint_result.get("errors", []),
                "lint_warnings": lint_result.get("warnings", []),
            }
        )
        write_dream_task(agent.memory_dir, task)
        write_dream_report(task, lint_result, changed_files, result)
        candidate_at = now()
        state.update(
            {
                "last_scan_at": datetime.fromtimestamp(scan_cutoff).isoformat(),
                "last_candidate_at": candidate_at,
                "last_success_at": candidate_at,
                "pending_session_ids": pending,
                "last_task_id": task_id,
            }
        )
        write_dream_state(agent.memory_dir, state)
        agent.last_dream_changed_files = changed_files
        agent.last_dream_task_id = task_id
        agent.session_event_bus.emit(
            "dream_consolidated",
            {
                "quiet": bool(quiet),
                "trigger": trigger,
                "task_id": task_id,
                "session_ids": selected_session_ids,
                "memory_dir": str(agent.memory_dir),
                "candidate_store": str(candidate_store),
                "changed_files": changed_files,
                "lint_status": lint_result["status"],
            },
        )
        agent.memory.state = memorylib.normalize_memory_state(agent.memory.state, agent.root)
        agent.session["memory"] = agent.memory.to_dict()
        summary = [
            f"Dream task {task_id} created.",
            f"status: {task['status']}",
            f"lint: {lint_result['status']}",
            f"candidate: {candidate_store.relative_to(agent.root).as_posix()}",
        ]
        if changed_files:
            summary.append("changed:")
            summary.extend(f"- {path}" for path in changed_files)
        if str(result).strip():
            summary.extend(["model:", str(result).strip()])
        return "\n".join(summary)
    except Exception as exc:
        task.update({"status": "failed", "ended_at": now(), "error": str(exc)})
        write_dream_task(agent.memory_dir, task)
        state.update(
            {
                "failed_session_ids": _dedupe_preserve_order(
                    [*state.get("failed_session_ids", []), *selected_session_ids]
                ),
                "last_task_id": task_id,
            }
        )
        write_dream_state(agent.memory_dir, state)
        raise
