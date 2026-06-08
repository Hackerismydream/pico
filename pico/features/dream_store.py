import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..core.workspace import now

ENTRYPOINT_NAME = "MEMORY.md"
LOCK_FILE_NAME = ".consolidate-lock"
DREAM_DIR_NAME = ".dream"
DREAM_LOCK_FILE_NAME = "lock"
DREAM_STATE_NAME = "state.json"
HOLDER_STALE_S = 3600


class DreamLockHeld(RuntimeError):
    pass


class DreamLock:
    def __init__(self, memory_dir):
        self.memory_dir = memory_dir

    @contextmanager
    def acquire(self, purpose="dream", task_id=""):
        if not try_acquire_dream_lock(self.memory_dir, purpose=purpose, task_id=task_id):
            raise DreamLockHeld("Dream already running.")
        try:
            yield
        finally:
            release_dream_lock(self.memory_dir)


def _ensure_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def ensure_memory_dir(memory_dir):
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "logs").mkdir(parents=True, exist_ok=True)
    (memory_dir / "topics").mkdir(parents=True, exist_ok=True)
    index_path = memory_dir / ENTRYPOINT_NAME
    if not index_path.exists():
        index_path.write_text(
            "# Durable Memory Index\n\n"
            "_Empty. `/remember` writes a daily log entry; `/dream` consolidates "
            "logs into topic files and adds entries here._\n",
            encoding="utf-8",
        )
    return memory_dir


def lock_path(memory_dir):
    return Path(memory_dir) / LOCK_FILE_NAME


def dream_dir(memory_dir):
    return Path(memory_dir) / DREAM_DIR_NAME


def dream_lock_path(memory_dir):
    return dream_dir(memory_dir) / DREAM_LOCK_FILE_NAME


def dream_state_path(memory_dir):
    return dream_dir(memory_dir) / DREAM_STATE_NAME


def dream_runs_dir(memory_dir):
    return dream_dir(memory_dir) / "runs"


def dream_snapshots_dir(memory_dir):
    return dream_dir(memory_dir) / "snapshots"


def iso_to_timestamp(value):
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return 0.0


def default_dream_state():
    return {
        "last_scan_at": "",
        "last_candidate_at": "",
        "last_apply_at": "",
        "last_success_at": "",
        "pending_session_ids": [],
        "processed_session_ids": [],
        "failed_session_ids": [],
        "last_task_id": "",
    }


def load_dream_state(memory_dir):
    path = dream_state_path(memory_dir)
    state = default_dream_state()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return state
    if not isinstance(loaded, dict):
        return state
    state.update({key: loaded.get(key, value) for key, value in state.items()})
    for key in ("pending_session_ids", "processed_session_ids", "failed_session_ids"):
        state[key] = _dedupe_preserve_order(str(item) for item in _ensure_list(state.get(key)))
    state["last_success_at"] = str(state.get("last_success_at", ""))
    state["last_task_id"] = str(state.get("last_task_id", ""))
    return state


def write_dream_state(memory_dir, state):
    path = dream_state_path(memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = default_dream_state()
    normalized.update(state or {})
    for key in ("pending_session_ids", "processed_session_ids", "failed_session_ids"):
        normalized[key] = _dedupe_preserve_order(str(item) for item in _ensure_list(normalized.get(key)))
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def read_last_consolidated_at(memory_dir):
    state = load_dream_state(memory_dir)
    state_ts = iso_to_timestamp(state.get("last_scan_at")) or iso_to_timestamp(state.get("last_success_at"))
    if state_ts > 0:
        return state_ts
    try:
        return lock_path(memory_dir).stat().st_mtime
    except OSError:
        return 0.0


def _lock_holder_pid(text):
    try:
        payload = json.loads(text)
        return int(payload.get("pid", 0))
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        try:
            return int(str(text).strip())
        except ValueError:
            return 0


def _lock_pid_is_live(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def try_acquire_dream_lock(memory_dir, purpose="dream", task_id=""):
    ensure_memory_dir(memory_dir)
    path = dream_lock_path(memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "purpose": purpose,
        "task_id": task_id,
        "created_at": now(),
    }
    for _attempt in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stat = path.stat()
                age = datetime.now().timestamp() - stat.st_mtime
                holder_pid = _lock_holder_pid(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                return False
            if age < HOLDER_STALE_S and _lock_pid_is_live(holder_pid):
                return False
            try:
                path.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return True
    return False


def release_dream_lock(memory_dir):
    path = dream_lock_path(memory_dir)
    try:
        path.unlink()
    except OSError:
        pass


def runtime_memory_parts(path):
    try:
        return Path(path).parts
    except TypeError:
        return ()


def is_runtime_memory_path(relative_path):
    parts = runtime_memory_parts(relative_path)
    return bool(parts and parts[0] in {"logs", DREAM_DIR_NAME, LOCK_FILE_NAME})


def is_official_memory_payload(relative_path):
    path = Path(relative_path)
    if path.as_posix() == ENTRYPOINT_NAME:
        return True
    return len(path.parts) >= 2 and path.parts[0] == "topics" and path.suffix == ".md"


def copy_memory_tree(source, target):
    source = Path(source)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        ensure_memory_dir(target)
        return

    def ignore(_dir, names):
        return {name for name in names if name == DREAM_DIR_NAME}

    shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore)
    ensure_memory_dir(target)


def collect_non_runtime_files(root):
    root = Path(root)
    result = {}
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if is_runtime_memory_path(relative):
            continue
        try:
            result[relative] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return result


def official_payload_texts(root):
    return {
        relative: text
        for relative, text in collect_non_runtime_files(root).items()
        if is_official_memory_payload(relative)
    }


def hash_texts(texts):
    return {relative: hashlib.sha256(text.encode("utf-8")).hexdigest() for relative, text in sorted(texts.items())}


def official_payload_hashes(root):
    return hash_texts(official_payload_texts(root))


def apply_candidate_payload(candidate_root, memory_dir):
    candidate_root = Path(candidate_root)
    memory_dir = Path(memory_dir)
    before = official_payload_texts(memory_dir)
    after = official_payload_texts(candidate_root)
    for relative in sorted(set(before) - set(after)):
        target = memory_dir / relative
        try:
            target.unlink()
        except OSError:
            pass
    for relative in sorted(after):
        source = candidate_root / relative
        target = memory_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    topics_dir = memory_dir / "topics"
    for directory in sorted(topics_dir.glob("**/*"), reverse=True) if topics_dir.exists() else []:
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def task_path(memory_dir, task_id, name):
    return dream_runs_dir(memory_dir) / task_id / name


def load_dream_task(memory_dir, task_id):
    path = task_path(memory_dir, task_id, "task.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_dream_task(memory_dir, task):
    path = task_path(memory_dir, task["id"], "task.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return task
