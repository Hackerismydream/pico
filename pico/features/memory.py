"""多步 agent 运行时使用的轻量工作记忆。

session history 负责保存完整事件流；这个模块只保存更小的一层工作集：
当前任务摘要、最近接触的文件、文件短摘要，以及少量跨轮笔记。
这样下一轮 prompt 还能接上上一轮，但不会被整段历史塞满。
"""

import hashlib
import difflib
import json
import os
import shutil
import threading
from datetime import date, datetime
import re
from pathlib import Path

from ..core.workspace import WorkspaceContext, clip, now
from .dream_lint import BASE64_LIKE_PATTERN, SECRET_VALUE_PATTERN

WORKING_FILE_LIMIT = 8
EPISODIC_NOTE_LIMIT = 12
FILE_SUMMARY_LIMIT = 6
MAX_MEMORY_INDEX_CHARS = 10000
MAX_ENTRYPOINT_LINES = 200
ENTRYPOINT_NAME = "MEMORY.md"
LOCK_FILE_NAME = ".consolidate-lock"
DREAM_DIR_NAME = ".dream"
DREAM_LOCK_FILE_NAME = "lock"
DREAM_STATE_NAME = "state.json"
HOLDER_STALE_S = 3600
# 单次 dream 最多消化的 session 数。超出时 dream prompt 只列最近 N 个，
# 防止 75+ session ID 撑爆模型上下文导致 empty_response。
DREAM_SESSION_CAP = 30
# dream 任务需要更多输出 token（要写多个 topic 文件 + 更新索引）。
DREAM_MIN_NEW_TOKENS = 4096

DURABLE_MEMORY_INTENT_PATTERN = re.compile(r"(?i)\b(capture|remember|save|store|persist|note)\b")
DURABLE_MEMORY_INTENT_ZH_PATTERN = re.compile(r"(记住|保存|记录|沉淀|长期记忆|持久记忆)")
DURABLE_MEMORY_LIST_PREFIX_PATTERN = re.compile(r"^(?:[-*]|\d+[.)])\s+")
DURABLE_MEMORY_LINE_PATTERNS = (
    ("project-conventions", re.compile(r"(?i)^Project convention:\s*(.+)$")),
    ("key-decisions", re.compile(r"(?i)^Decision:\s*(.+)$")),
    ("dependency-facts", re.compile(r"(?i)^Dependency:\s*(.+)$")),
    ("user-preferences", re.compile(r"(?i)^Preference:\s*(.+)$")),
    ("project-conventions", re.compile(r"^项目约定：\s*(.+)$")),
    ("key-decisions", re.compile(r"^决策：\s*(.+)$")),
    ("dependency-facts", re.compile(r"^依赖：\s*(.+)$")),
    ("user-preferences", re.compile(r"^偏好：\s*(.+)$")),
)
SECRET_SHAPED_TEXT_PATTERN = re.compile(r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})")
APPLICABLE_DREAM_STATUSES = {"completed_candidate", "completed_with_warnings"}

DURABLE_TOPIC_DEFAULTS = {
    "project-conventions": {
        "title": "Project Conventions",
        "summary": "Stable repository conventions.",
        "tags": ["convention"],
    },
    "key-decisions": {
        "title": "Key Decisions",
        "summary": "Long-lived decisions and rationale anchors.",
        "tags": ["decision"],
    },
    "dependency-facts": {
        "title": "Dependency Facts",
        "summary": "Stable dependency and environment facts.",
        "tags": ["dependency"],
    },
    "user-preferences": {
        "title": "User Preferences",
        "summary": "Stable user preferences.",
        "tags": ["preference"],
    },
}


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


class DreamLockHeld(RuntimeError):
    pass


class DreamApplyError(RuntimeError):
    pass


def daily_log_path(memory_dir, today=None):
    today = today or date.today()
    memory_dir = ensure_memory_dir(memory_dir)
    path = memory_dir / "logs" / str(today.year) / f"{today.month:02d}" / f"{today.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_to_daily_log(memory_dir, entry, today=None):
    entry = str(entry).strip()
    if not entry:
        return None
    path = daily_log_path(memory_dir, today=today)
    timestamp = datetime.now().strftime("%H:%M")
    with path.open("a", encoding="utf-8") as file:
        file.write(f"- [{timestamp}] {entry}\n")
    return path


def default_memory_maintenance_audit(auto_dream=True):
    return {
        "memory_tags_appended": [],
        "auto_dream": {
            "enabled": bool(auto_dream),
            "triggered": False,
            "skip_reason": "",
            "session_count": 0,
            "session_ids": [],
            "changed_files": [],
        },
        "errors": [],
    }


def _agent_relative_path(agent, path):
    try:
        return Path(path).resolve().relative_to(agent.root).as_posix()
    except ValueError:
        return str(path)


def _emit_memory_trace(agent, event, payload):
    task_state = getattr(agent, "current_task_state", None)
    if task_state is None:
        return None
    return agent.emit_trace(task_state, event, payload)


def _write_memory_maintenance_report(agent, task_state, audit):
    try:
        if agent.run_store.report_path(task_state).exists():
            report = agent.run_store.load_report(task_state)
        else:
            report = agent.build_report(task_state)
    except (OSError, json.JSONDecodeError):
        report = agent.build_report(task_state)
    report["memory_maintenance"] = dict(audit)
    agent.run_store.write_report(task_state, agent.redact_artifact(report))


def load_memory_index_text(memory_dir):
    path = Path(memory_dir) / ENTRYPOINT_NAME
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_MEMORY_INDEX_CHARS]
    except OSError:
        return ""
    # 占位模板里没有实际 topic 条目（行首 "- [name]"），视作空索引，
    # 让 /memory 显示"No durable memories yet"提示而不是占位文本。
    if not any(line.lstrip().startswith("- [") for line in text.splitlines()):
        return ""
    return text


def extract_memory_tags(text):
    return [match.strip() for match in re.findall(r"<memory>(.*?)</memory>", str(text), re.DOTALL) if match.strip()]


def _lock_path(memory_dir):
    return Path(memory_dir) / LOCK_FILE_NAME


def _dream_dir(memory_dir):
    return Path(memory_dir) / DREAM_DIR_NAME


def _dream_lock_path(memory_dir):
    return _dream_dir(memory_dir) / DREAM_LOCK_FILE_NAME


def _dream_state_path(memory_dir):
    return _dream_dir(memory_dir) / DREAM_STATE_NAME


def _dream_runs_dir(memory_dir):
    return _dream_dir(memory_dir) / "runs"


def _dream_snapshots_dir(memory_dir):
    return _dream_dir(memory_dir) / "snapshots"


def _iso_to_timestamp(value):
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
    path = _dream_state_path(memory_dir)
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
    path = _dream_state_path(memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = default_dream_state()
    normalized.update(state or {})
    for key in ("pending_session_ids", "processed_session_ids", "failed_session_ids"):
        normalized[key] = _dedupe_preserve_order(str(item) for item in _ensure_list(normalized.get(key)))
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def read_last_consolidated_at(memory_dir):
    state = load_dream_state(memory_dir)
    state_ts = _iso_to_timestamp(state.get("last_scan_at")) or _iso_to_timestamp(state.get("last_success_at"))
    if state_ts > 0:
        return state_ts
    try:
        return _lock_path(memory_dir).stat().st_mtime
    except OSError:
        return 0.0


def try_acquire_lock(memory_dir):
    ensure_memory_dir(memory_dir)
    lock_path = _lock_path(memory_dir)
    current_pid = os.getpid()
    try:
        stat = lock_path.stat()
        age = datetime.now().timestamp() - stat.st_mtime
        holder_pid = int(lock_path.read_text(encoding="utf-8").strip())
        if age < HOLDER_STALE_S:
            try:
                os.kill(holder_pid, 0)
                return False
            except OSError:
                pass
    except (OSError, ValueError):
        pass
    lock_path.write_text(str(current_pid), encoding="utf-8")
    return True


def release_lock(memory_dir):
    lock_path = _lock_path(memory_dir)
    try:
        timestamp = datetime.now().timestamp()
        lock_path.write_text("released", encoding="utf-8")
        os.utime(lock_path, (timestamp, timestamp))
    except OSError:
        pass


def record_consolidation(memory_dir):
    ensure_memory_dir(memory_dir)
    lock_path = _lock_path(memory_dir)
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    timestamp = datetime.now().timestamp()
    os.utime(lock_path, (timestamp, timestamp))


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
    lock_path = _dream_lock_path(memory_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "purpose": purpose,
        "task_id": task_id,
        "created_at": now(),
    }
    for _attempt in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stat = lock_path.stat()
                age = datetime.now().timestamp() - stat.st_mtime
                holder_pid = _lock_holder_pid(lock_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                return False
            if age < HOLDER_STALE_S and _lock_pid_is_live(holder_pid):
                return False
            try:
                lock_path.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return True
    return False


def release_dream_lock(memory_dir):
    lock_path = _dream_lock_path(memory_dir)
    try:
        lock_path.unlink()
    except OSError:
        pass


def list_sessions_since(since_ts, sessions_dir=None, current_session_id="", until_ts=None):
    scan_dir = Path(sessions_dir) if sessions_dir is not None else None
    if scan_dir is None or not scan_dir.exists():
        return []
    result = set()
    for path in scan_dir.iterdir():
        if path.suffix not in {".json", ".jsonl"}:
            continue
        session_id = path.stem.removesuffix(".events")
        if current_session_id and current_session_id == session_id:
            continue
        mtime = path.stat().st_mtime
        if mtime > since_ts and (until_ts is None or mtime <= until_ts):
            result.add(session_id)
    return sorted(result)


def should_auto_dream(memory_dir, min_hours, min_sessions, current_session_id, sessions_dir=None):
    return evaluate_auto_dream_gate(memory_dir, min_hours, min_sessions, current_session_id, sessions_dir=sessions_dir)["should_run"]


def evaluate_auto_dream_gate(memory_dir, min_hours, min_sessions, current_session_id, sessions_dir=None):
    last = read_last_consolidated_at(memory_dir)
    scan_cutoff = datetime.now().timestamp()
    hours_since = (scan_cutoff - last) / 3600 if last > 0 else float("inf")
    state = load_dream_state(memory_dir)
    processed = set(state.get("processed_session_ids", []))
    pending = [session_id for session_id in state.get("pending_session_ids", []) if session_id not in processed]
    new_sessions = list_sessions_since(last, sessions_dir=sessions_dir, current_session_id=current_session_id, until_ts=scan_cutoff)
    session_ids = sorted({session_id for session_id in pending + new_sessions if session_id not in processed})
    result = {
        "should_run": False,
        "skip_reason": "",
        "session_count": len(session_ids),
        "session_ids": session_ids,
        "scan_cutoff": scan_cutoff,
    }
    if hours_since < float(min_hours):
        result["skip_reason"] = "interval_gate"
        return result
    if len(session_ids) < int(min_sessions):
        result["skip_reason"] = "session_gate"
        return result
    result["should_run"] = True
    return result


def build_memory_system_section(memory_dir):
    index = load_memory_index_text(memory_dir)
    if index:
        index_section = f"## Current Memory Index ({ENTRYPOINT_NAME})\n{index}\n"
    else:
        index_section = "No durable memories consolidated yet.\n"
    section = f"""# Auto Memory

You have a persistent, file-based memory system at `{Path(memory_dir)}/`.
This directory already exists. Write to it directly with memory-safe file tools; do not create a second memory store.

## Critical memory contract
- `/remember <text>` appends a note to the daily log.
- `/memory` prints the durable memory index.
- `/dream` consolidates daily logs into memory files and updates `{ENTRYPOINT_NAME}`.
- Structured memory files must use frontmatter: `name`, `description`, and `type`.
- Allowed `type` values are `user`, `feedback`, `project`, and `reference`.
- MEMORY.md is an index, not a memory. Keep it under {MAX_ENTRYPOINT_LINES} lines.
- If the user asks you to forget something, find and remove the relevant entry.

{index_section}
Build this memory system over time so future sessions can understand who the user is, how they prefer to collaborate, what behavior to avoid or repeat, and the context behind long-running work.

If the user explicitly asks you to remember something, save it immediately using whichever type fits best. If they ask you to forget something, find and remove the relevant entry instead of adding a contradiction.

## Types of memory

There are four discrete types of memory:

### user
Information about the user's role, goals, responsibilities, knowledge, and collaboration preferences.
**When to save:** When you learn stable details about the user's role, goals, responsibilities, preferences, or knowledge.

### feedback
Guidance or correction the user has given you that should change future behavior.
**When to save:** Any time the user corrects your approach in a way applicable to future conversations.
**Body structure:** Lead with the rule, then a **Why:** line and a **How to apply:** line.

### project
Information about ongoing work, goals, initiatives, bugs, incidents, or decisions not directly derivable from code or git history.
**When to save:** When you learn who is doing what, why, or by when. Always convert relative dates to absolute dates.
**Body structure:** Lead with the fact or decision, then **Why:** and **How to apply:** lines.

### reference
Pointers to where information lives in external systems and why it matters.
**When to save:** When you learn about a resource, external system, document, issue tracker, dataset, or link that future sessions should know how to find.

## What NOT to save
- Code patterns, architecture, file paths, or APIs that are derivable from reading the project
- Git history or recent changes; git is authoritative
- Debugging solutions where the fix is already in code or commit history
- Secrets, credentials, tokens, private keys, or secret-shaped values
- Raw command output, stack traces, or long logs
- Ephemeral task details, current blockers, next steps, or transient conversation context

## How to save memories

**Option A — <memory> tags (quick notes):**
Wrap text in `<memory>...</memory>` tags in your final answer. These are automatically extracted and appended to the daily log.

**Option B - Write files directly (structured memories):**
Write a `.md` file under `{Path(memory_dir)}/` with this frontmatter:

```markdown
---
name: {{{{memory name}}}}
description: {{{{one-line description — used to decide relevance later}}}}
type: {{{{user | feedback | project | reference}}}}
---

{{{{memory content}}}}
```

Then add a pointer to that file in `{Path(memory_dir)}/{ENTRYPOINT_NAME}`. MEMORY.md is an index, not a memory; it should contain only links with brief descriptions. Keep it under {MAX_ENTRYPOINT_LINES} lines.

## When to access memories
- When specific known memories seem relevant to the task at hand
- When the user seems to be referring to work from a prior conversation
- You MUST access memory when the user explicitly asks you to recall or remember

## Slash commands
- `/remember <text>` appends a note to the daily log.
- `/memory` prints the durable memory index.
- `/dream` consolidates daily logs into memory files and updates `{ENTRYPOINT_NAME}`.
"""
    return section


def build_dream_prompt(memory_dir, transcript_dir="", session_ids=None):
    session_ids = list(session_ids or [])
    total = len(session_ids)
    truncated = False
    if total > DREAM_SESSION_CAP:
        session_ids = session_ids[-DREAM_SESSION_CAP:]
        truncated = True
    extra_parts = [
        "Tool constraints for this run: shell execution is not required. Writes must stay inside the memory directory. Read/search/list tools may be used to inspect existing memories and transcripts."
    ]
    if session_ids:
        header = (
            f"Sessions since last consolidation (showing the most recent {len(session_ids)} of {total}; "
            "consolidate these and the next dream will pick up the rest):"
            if truncated
            else "Sessions since last consolidation:"
        )
        extra_parts.append(header + "\n" + "\n".join(f"- {session_id}" for session_id in session_ids))
    extra_section = "\n\n## Additional context\n\n" + "\n\n".join(extra_parts)
    transcript_line = ""
    if transcript_dir:
        transcript_line = (
            f"\nSession transcripts: `{transcript_dir}` (large JSONL files — search narrowly, do not read whole files).\n"
        )

    return f"""# Dream: Memory Consolidation

You are performing a dream: a reflective pass over Pico's memory files. Synthesize recent signal into durable, well-organized memory files so future sessions can orient quickly.

Memory directory: `{Path(memory_dir)}`
This directory already exists. Write to it directly; do not create a second memory store.
{transcript_line}
Daily logs live under `logs/YYYY/MM/YYYY-MM-DD.md`.
The memory index is `{ENTRYPOINT_NAME}`.

## Phase 1 - Orient

- List files in `{Path(memory_dir)}/` to see what already exists.
- Read `{ENTRYPOINT_NAME}` if it exists to understand the current index.
- Skim existing topic files so you improve them instead of creating duplicates.
- If `logs/` or session transcript files exist, review recent entries first.

## Phase 2 - Gather recent signal

Look for new information worth persisting. Sources in rough priority order:

1. Daily logs (`logs/YYYY/MM/YYYY-MM-DD.md`) - these are the append-only memory intake stream.
2. Existing memories that drifted - facts that contradict what you now know.
3. Transcript search - if you need specific context, use narrow grep-style terms:
   `grep -rn "<narrow term>" {transcript_dir}/ --include="*.jsonl" | tail -50`

Do not exhaustively read transcripts. Look only for things you already suspect matter.

## Phase 3 - Consolidate

For each thing worth remembering, write or update a memory file using the memory file format and type conventions from the Auto Memory section. Use the memory file format and type conventions as the source of truth for what to save, how to structure it, and what NOT to save.

Focus on:
- Merging new signal into existing topic files rather than creating near-duplicates.
- Converting relative dates ("yesterday", "last week") to absolute dates so they remain interpretable after time passes.
- Deleting contradicted facts; if current evidence disproves an old memory, fix it at the source.
- Keeping secrets, raw command output, stack traces, and transient task state out of memory files.

## Phase 4 - Prune and index

Update `{ENTRYPOINT_NAME}` so it stays under {MAX_ENTRYPOINT_LINES} lines and under ~25KB. It is an index, not a dump; each entry should be one line under ~150 characters, like `- [Title](file.md) — one-line hook`. Never write memory content directly into it.

- Remove pointers to memories that are now stale, wrong, or superseded.
- Demote verbose index entries into topic files.
- Add pointers to newly important memories.
- Resolve contradictions by fixing the wrong memory file, not by adding a second contradictory entry.

Return a brief summary of what you consolidated, updated, or pruned. If nothing changed, say so.{extra_section}"""


def reject_durable_reason(note_text, redacted_value="<redacted>"):
    text = str(note_text or "").strip()
    lowered = text.lower()
    if not text:
        return "empty"
    if redacted_value in text or SECRET_SHAPED_TEXT_PATTERN.search(text):
        return "secret_shaped"
    checkpoint_like_prefixes = (
        "current goal",
        "current blocker",
        "next step",
        "current phase",
        "key files",
        "freshness",
        "当前目标",
        "当前卡点",
        "下一步",
        "当前阶段",
        "关键文件",
        "已完成",
        "已排除",
    )
    if any(lowered.startswith(prefix) for prefix in checkpoint_like_prefixes):
        return "transient_task_state"
    if re.search(r"(?i)\b(stdout|stderr|traceback|exit_code)\b", text) or len(text) > 220:
        return "noisy_output"
    return ""


def extract_durable_promotions(user_message, final_answer, redacted_value="<redacted>"):
    user_text = str(user_message or "")
    if not (DURABLE_MEMORY_INTENT_PATTERN.search(user_text) or DURABLE_MEMORY_INTENT_ZH_PATTERN.search(user_text)):
        return [], []
    promotions = []
    rejections = []
    for line in str(final_answer or "").splitlines():
        text = DURABLE_MEMORY_LIST_PREFIX_PATTERN.sub("", line.strip(), count=1)
        if not text or redacted_value in text:
            continue
        for topic, pattern in DURABLE_MEMORY_LINE_PATTERNS:
            match = pattern.match(text)
            if not match:
                continue
            note_text = match.group(1).strip()
            if note_text:
                reason = reject_durable_reason(note_text, redacted_value=redacted_value)
                if reason:
                    rejections.append(f"{topic}:{reason}")
                    break
                promotions.append((topic, note_text))
            break
    return promotions, rejections


def promote_durable_memory(agent, user_message, final_answer):
    promotions, rejections = extract_durable_promotions(user_message, final_answer)
    promoted, superseded = agent.memory.promote_durable(promotions)
    agent.session["memory"] = agent.memory.to_dict()
    agent.last_durable_promotions = promoted
    agent.last_durable_rejections = rejections
    agent.last_durable_superseded = superseded
    return promoted, rejections, superseded


def _new_dream_task_id(trigger="manual"):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    suffix = hashlib.sha1(f"{stamp}-{os.getpid()}-{trigger}".encode("utf-8")).hexdigest()[:6]
    return f"dream_{stamp}_{suffix}"


def _runtime_memory_parts(path):
    try:
        return Path(path).parts
    except TypeError:
        return ()


def _is_runtime_memory_path(relative_path):
    parts = _runtime_memory_parts(relative_path)
    return bool(parts and parts[0] in {"logs", DREAM_DIR_NAME, LOCK_FILE_NAME})


def _is_official_memory_payload(relative_path):
    path = Path(relative_path)
    if path.as_posix() == ENTRYPOINT_NAME:
        return True
    return len(path.parts) >= 2 and path.parts[0] == "topics" and path.suffix == ".md"


def _copy_memory_tree(source, target):
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


def _managed_file_texts(root):
    root = Path(root)
    result = {}
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _is_runtime_memory_path(relative):
            continue
        try:
            result[relative] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return result


def _official_payload_texts(root):
    return {
        relative: text
        for relative, text in _managed_file_texts(root).items()
        if _is_official_memory_payload(relative)
    }


def _hash_texts(texts):
    return {relative: hashlib.sha256(text.encode("utf-8")).hexdigest() for relative, text in sorted(texts.items())}


def _official_payload_hashes(root):
    return _hash_texts(_official_payload_texts(root))


def _redact_sensitive_text(text):
    text = SECRET_VALUE_PATTERN.sub("<redacted>", str(text))
    return BASE64_LIKE_PATTERN.sub("<redacted>", text)


def _write_dream_diff(before_root, candidate_root, diff_path):
    before = _managed_file_texts(before_root)
    after = _managed_file_texts(candidate_root)
    lines = []
    for relative in sorted(set(before) | set(after)):
        old_lines = before.get(relative, "").splitlines()
        new_lines = after.get(relative, "").splitlines()
        if old_lines == new_lines:
            continue
        lines.extend(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"official/{relative}",
                tofile=f"candidate/{relative}",
                lineterm="",
            )
        )
        lines.append("\n")
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_text = _redact_sensitive_text("\n".join(lines).rstrip() + ("\n" if lines else ""))
    diff_path.write_text(diff_text, encoding="utf-8")
    return sorted(relative for relative in set(before) | set(after) if before.get(relative) != after.get(relative))


def _frontmatter(text):
    from .dream_lint import _frontmatter as _parse_frontmatter

    return _parse_frontmatter(text)


def _legacy_topic_metadata(text):
    from .dream_lint import _legacy_topic_metadata as _parse_legacy_topic_metadata

    return _parse_legacy_topic_metadata(text)


def lint_memory_candidate(candidate_root):
    from .dream_lint import lint_memory_candidate as _lint_memory_candidate

    return _lint_memory_candidate(candidate_root)


def _task_path(memory_dir, task_id, name):
    return _dream_runs_dir(memory_dir) / task_id / name


def load_dream_task(memory_dir, task_id):
    path = _task_path(memory_dir, task_id, "task.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_dream_task(memory_dir, task):
    path = _task_path(memory_dir, task["id"], "task.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return task


def _write_dream_report(task, lint_result, changed_files, model_result):
    report_path = Path(task["report_path"])
    lines = [
        f"# Dream Report: {task['id']}",
        "",
        f"- trigger: {task['trigger']}",
        f"- status: {task['status']}",
        f"- candidate: {task['candidate_store']}",
        f"- lint: {lint_result['status']}",
        "",
        "## Inputs",
    ]
    for session_id in task.get("input_sessions", []):
        lines.append(f"- session:{session_id}")
    if not task.get("input_sessions"):
        lines.append("- none")
    lines.extend(["", "## Changed files"])
    for path in changed_files:
        lines.append(f"- {path}")
    if not changed_files:
        lines.append("- none")
    lines.extend(["", "## Lint"])
    for issue in lint_result.get("errors", []):
        lines.append(f"- error:{issue['code']} {issue.get('path', '')}".rstrip())
    for warning in lint_result.get("warnings", []):
        lines.append(f"- warning:{warning['code']} {warning.get('path', '')}".rstrip())
    if not lint_result.get("errors") and not lint_result.get("warnings"):
        lines.append("- passed")
    lines.extend(["", "## Model result", _redact_sensitive_text(str(model_result).strip() or "(empty)")])
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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


def dream_review_text(agent, task_id):
    task = load_dream_task(agent.memory_dir, task_id)
    if not task:
        return f"error: dream task not found: {task_id}"
    parts = [
        dream_status_text_for_task(task),
        "",
        "Changed files:",
    ]
    for path in task.get("changed_files", []):
        parts.append(f"- {path}")
    if not task.get("changed_files"):
        parts.append("- none")
    diff_path = Path(task.get("diff_path", ""))
    if diff_path.exists():
        diff = clip(_redact_sensitive_text(diff_path.read_text(encoding="utf-8", errors="replace")), 4000)
        parts.extend(["", "Diff:", diff or "(empty)"])
    return "\n".join(parts)


def dream_status_text_for_task(task):
    lines = [
        f"dream: {task.get('id', '')}",
        f"status: {task.get('status', 'unknown')}",
        f"lint: {task.get('lint_status', 'unknown')}",
    ]
    for issue in task.get("lint_errors", []):
        lines.append(f"error: {issue.get('code', '')} {issue.get('path', '')}".rstrip())
    for warning in task.get("lint_warnings", []):
        lines.append(f"warning: {warning.get('code', '')} {warning.get('path', '')}".rstrip())
    return "\n".join(lines)


def _copy_managed_candidate_to_official(candidate_root, memory_dir):
    candidate_root = Path(candidate_root)
    memory_dir = Path(memory_dir)
    before = _official_payload_texts(memory_dir)
    after = _official_payload_texts(candidate_root)
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
    for directory in sorted((memory_dir / "topics").glob("**/*"), reverse=True) if (memory_dir / "topics").exists() else []:
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def apply_dream_task(agent, task_id):
    if not try_acquire_dream_lock(agent.memory_dir, purpose="apply", task_id=task_id):
        raise DreamApplyError("Dream already running.")
    try:
        task = load_dream_task(agent.memory_dir, task_id)
        if not task:
            raise DreamApplyError(f"dream task not found: {task_id}")
        if task.get("status") == "applied":
            return f"Dream task already applied: {task_id}"
        if task.get("status") not in APPLICABLE_DREAM_STATUSES:
            raise DreamApplyError(f"dream task cannot be applied with status: {task.get('status', 'unknown')}")
        candidate = Path(task["candidate_store"])
        if not candidate.exists():
            raise DreamApplyError(f"dream candidate missing: {candidate}")

        lint_result = lint_memory_candidate(candidate)
        changed_files = _write_dream_diff(Path(task.get("input_snapshot", "")), candidate, Path(task["diff_path"]))
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
            _write_dream_task(agent.memory_dir, task)
            raise DreamApplyError(f"dream task cannot be applied with lint status: {lint_result['status']}")

        base_files = task.get("base_files", {})
        current_files = _official_payload_hashes(agent.memory_dir)
        if base_files != current_files:
            _write_dream_task(agent.memory_dir, task)
            raise DreamApplyError("official memory changed since candidate was created; rerun /dream")

        snapshot_id = f"snapshot_{datetime.now().strftime('%Y%m%d-%H%M%S')}_{task_id}"
        snapshot_path = _dream_snapshots_dir(agent.memory_dir) / snapshot_id
        _copy_memory_tree(agent.memory_dir, snapshot_path)
        _copy_managed_candidate_to_official(candidate, agent.memory_dir)
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
        _write_dream_task(agent.memory_dir, task)
        agent.memory.state = normalize_memory_state(agent.memory.state, agent.root)
        agent.session["memory"] = agent.memory.to_dict()
        return f"Applied dream task {task_id}.\nsnapshot: {snapshot_id}"
    finally:
        release_dream_lock(agent.memory_dir)


def discard_dream_task(agent, task_id):
    task = load_dream_task(agent.memory_dir, task_id)
    if not task:
        return f"error: dream task not found: {task_id}"
    if task.get("status") == "applied":
        return f"error: dream task already applied: {task_id}"
    task["status"] = "discarded"
    task["discarded_at"] = now()
    _write_dream_task(agent.memory_dir, task)
    return f"Discarded dream task {task_id}."


def run_dream(agent, quiet=False, session_ids=None, trigger="manual", raise_on_lock=False, scan_cutoff=None):
    from ..core.runtime import Pico

    ensure_memory_dir(agent.memory_dir)
    if not try_acquire_dream_lock(agent.memory_dir, purpose="generate", task_id=""):
        if raise_on_lock:
            raise DreamLockHeld("dream already running")
        return "Dream already running."
    state = load_dream_state(agent.memory_dir)
    discovered = list(session_ids or [])
    processed = set(state.get("processed_session_ids", []))
    pending = _dedupe_preserve_order([*state.get("pending_session_ids", []), *discovered])
    pending = [session_id for session_id in pending if session_id not in processed]
    selected_session_ids = pending[:DREAM_SESSION_CAP]
    scan_cutoff = float(scan_cutoff or datetime.now().timestamp())
    task_id = _new_dream_task_id(trigger=trigger)
    run_dir = _dream_runs_dir(agent.memory_dir) / task_id
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
    _write_dream_task(agent.memory_dir, task)
    try:
        base_files = _official_payload_hashes(agent.memory_dir)
        _copy_memory_tree(agent.memory_dir, input_snapshot)
        _copy_memory_tree(agent.memory_dir, candidate_store)
        task["base_files"] = base_files
        _write_dream_task(agent.memory_dir, task)
        dream_prompt = build_dream_prompt(candidate_store, transcript_dir=str(agent.session_store.root), session_ids=selected_session_ids)
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
            max_new_tokens=max(agent.max_new_tokens, DREAM_MIN_NEW_TOKENS),
            secret_env_names=agent.secret_env_names,
            feature_flags={**agent.feature_flags, "memory": False, "relevant_memory": False},
            write_scope=[str(memory_scope)],
            memory_dir=agent.memory_dir,
            auto_dream=False,
        )
        dream_agent.set_tool_profile("dream")
        dream_agent.refresh_prefix(force=True)
        result = dream_agent.ask(dream_prompt)
        changed_files = _write_dream_diff(input_snapshot, candidate_store, diff_path)
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
        _write_dream_task(agent.memory_dir, task)
        _write_dream_report(task, lint_result, changed_files, result)
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
        agent.memory.state = normalize_memory_state(agent.memory.state, agent.root)
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
        _write_dream_task(agent.memory_dir, task)
        state.update({"failed_session_ids": _dedupe_preserve_order([*state.get("failed_session_ids", []), *selected_session_ids]), "last_task_id": task_id})
        write_dream_state(agent.memory_dir, state)
        raise
    finally:
        release_dream_lock(agent.memory_dir)


def maintain_memory_after_turn(agent, final_answer):
    audit = default_memory_maintenance_audit(auto_dream=agent.auto_dream)
    agent.last_memory_maintenance = audit
    for entry in extract_memory_tags(final_answer):
        path = append_to_daily_log(agent.memory_dir, entry)
        payload = {"source": "final_answer", "path": _agent_relative_path(agent, path), "chars": len(entry)}
        audit["memory_tags_appended"].append(payload)
        agent.session_event_bus.emit("memory_note_appended", payload)
    if not agent.auto_dream:
        audit["auto_dream"]["skip_reason"] = "disabled"
        _emit_memory_trace(agent, "memory_auto_dream_skipped", dict(audit["auto_dream"]))
        return audit
    gate = evaluate_auto_dream_gate(
        agent.memory_dir,
        min_hours=agent.dream_interval_hours,
        min_sessions=agent.dream_min_sessions,
        current_session_id=agent.session["id"],
        sessions_dir=agent.session_store.root,
    )
    audit["auto_dream"]["session_count"] = gate["session_count"]
    audit["auto_dream"]["session_ids"] = list(gate["session_ids"])
    if not gate["should_run"]:
        audit["auto_dream"]["skip_reason"] = gate["skip_reason"]
        _emit_memory_trace(agent, "memory_auto_dream_skipped", dict(audit["auto_dream"]))
        return audit
    session_ids = list(gate["session_ids"])
    task_state = getattr(agent, "current_task_state", None)
    audit["auto_dream"]["triggered"] = True
    audit["auto_dream"]["status"] = "submitted"
    started_payload = {"session_ids": session_ids, "session_count": len(session_ids), "status": "submitted"}
    agent.session_event_bus.emit("auto_dream_started", started_payload)
    _emit_memory_trace(agent, "memory_auto_dream_started", started_payload)

    def _background_dream():
        try:
            run_dream(agent, quiet=True, session_ids=session_ids, trigger="auto", raise_on_lock=True, scan_cutoff=gate["scan_cutoff"])
            audit["auto_dream"]["status"] = "finished"
            audit["auto_dream"]["changed_files"] = list(getattr(agent, "last_dream_changed_files", []))
            audit["auto_dream"]["task_id"] = getattr(agent, "last_dream_task_id", "")
            _emit_memory_trace(agent, "memory_auto_dream_finished", dict(audit["auto_dream"]))
        except DreamLockHeld:
            audit["auto_dream"]["status"] = "skipped"
            audit["auto_dream"]["skip_reason"] = "lock_held"
            _emit_memory_trace(agent, "memory_auto_dream_skipped", dict(audit["auto_dream"]))
        except Exception as exc:
            audit["auto_dream"]["status"] = "failed"
            audit["errors"].append(str(exc))
            agent.session_event_bus.emit("memory_auto_dream_failed", {"error": clip(str(exc), 300), "session_ids": session_ids})
            _emit_memory_trace(agent, "memory_auto_dream_failed", {"error": clip(str(exc), 300), "session_ids": session_ids})
        finally:
            if getattr(agent, "current_task_state", None) is task_state:
                agent.last_memory_maintenance = audit
            if task_state is not None:
                _write_memory_maintenance_report(agent, task_state, audit)

    thread = threading.Thread(target=_background_dream, name="pico-auto-dream", daemon=True)
    agent._memory_maintenance_thread = thread
    thread.start()
    return audit


def default_memory_state():
    # 用一个小而结构化的状态，而不是一大段自由文本摘要。
    return {
        "working": {
            "task_summary": "",
            "recent_files": [],
        },
        "episodic_notes": [],
        "file_summaries": {},
        "task": "",
        "files": [],
        "notes": [],
        "next_note_index": 0,
    }


class DurableMemoryStore:
    def __init__(self, root):
        self.root = Path(root)
        self.index_path = self.root / "MEMORY.md"
        self.topics_dir = self.root / "topics"

    def topic_slugs(self):
        return [topic["topic"] for topic in self.load_index()]

    def load_index(self):
        if not self.index_path.exists():
            return []
        lines = self.index_path.read_text(encoding="utf-8").splitlines()
        topics = []
        current = None
        for raw in lines:
            line = raw.strip()
            match = re.match(r"- \[([^\]]+)\]\(([^)]+)\)(?:\s*(?::|—|-)\s*(.*))?$", line)
            if match:
                topic_path = Path(match.group(2).strip())
                label = match.group(1).strip()
                description = (match.group(3) or "").strip()
                current = {
                    "topic": topic_path.stem or match.group(1).strip(),
                    "title": label,
                    "summary": description,
                    "tags": [],
                }
                topics.append(current)
                continue
            if current is None:
                continue
            summary_match = re.match(r"- summary:\s*(.+)", line)
            if summary_match:
                current["summary"] = summary_match.group(1).strip()
                continue
            tags_match = re.match(r"- tags:\s*(.+)", line)
            if tags_match:
                current["tags"] = [tag.strip() for tag in tags_match.group(1).split(",") if tag.strip()]
        return topics

    def load_topic_notes(self, topic):
        path = self.topics_dir / f"{topic}.md"
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        notes = []
        capture = False
        updated_at = ""
        tags = []
        metadata = _frontmatter(text) or {}
        in_frontmatter = text.startswith("---\n")
        for index, raw in enumerate(lines):
            line = raw.strip()
            if in_frontmatter:
                if index > 0 and line == "---":
                    in_frontmatter = False
                continue
            if line.startswith("- tags:"):
                tags = [tag.strip() for tag in line.split(":", 1)[1].split(",") if tag.strip()]
            elif line.startswith("- updated_at:"):
                updated_at = line.split(":", 1)[1].strip()
            elif line.startswith("## "):
                capture = True
            elif capture and line.startswith("- "):
                notes.append(
                    {
                        "text": line[2:].strip(),
                        "tags": tags,
                        "source": topic,
                        "created_at": updated_at or now(),
                        "kind": "durable",
                    }
                )
        if not notes and metadata.get("description"):
            notes.append(
                {
                    "text": metadata["description"],
                    "tags": tags,
                    "source": topic,
                    "created_at": updated_at or now(),
                    "kind": "durable",
                }
            )
        return notes

    @staticmethod
    def _subject_key(text):
        text = str(text).strip()
        patterns = (
            r"^(.+?)\s+is\s+.+$",
            r"^(.+?)\s+are\s+.+$",
            r"^(.+?)\s+uses?\s+.+$",
            r"^(.+?)\s+should\s+.+$",
            r"^(.+?)是.+$",
            r"^(.+?)使用.+$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, re.I)
            if match:
                subject = " ".join(_tokenize(match.group(1)))
                return subject or None
        return None

    def retrieval_candidates(self, query, limit=3):
        query_tokens = _tokenize(query)
        ranked = []
        for topic in self.load_index():
            notes = self.load_topic_notes(topic["topic"])
            for note in notes:
                note_tags = {tag.lower() for tag in note.get("tags", [])}
                note_tokens = _tokenize(note.get("text", "")) | _tokenize(topic.get("title", "")) | note_tags
                exact_tag_match = int(bool(query_tokens & note_tags))
                keyword_overlap = len(query_tokens & note_tokens)
                if exact_tag_match == 0 and keyword_overlap == 0:
                    continue
                recency = _parse_timestamp(note.get("created_at"))
                ranked.append(((exact_tag_match, keyword_overlap, recency), note))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in ranked[:limit]]

    def _write_index(self, topics):
        self.root.mkdir(parents=True, exist_ok=True)
        self.topics_dir.mkdir(parents=True, exist_ok=True)
        lines = ["# Durable Memory Index", ""]
        for topic in topics:
            lines.append(f"- [{topic['topic']}](topics/{topic['topic']}.md): {topic['title']}")
            lines.append(f"  - summary: {topic['summary']}")
            lines.append(f"  - tags: {', '.join(topic['tags'])}")
        self.index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _write_topic(self, topic, notes):
        self.topics_dir.mkdir(parents=True, exist_ok=True)
        meta = DURABLE_TOPIC_DEFAULTS[topic]
        lines = [
            f"# {meta['title']}",
            "",
            f"- topic: {topic}",
            f"- summary: {meta['summary']}",
            f"- tags: {', '.join(meta['tags'])}",
            f"- updated_at: {now()}",
            "",
            "## Notes",
        ]
        for note in notes:
            lines.append(f"- {note}")
        (self.topics_dir / f"{topic}.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def promote(self, promotions):
        if not promotions:
            return [], []
        topics = {topic["topic"]: topic for topic in self.load_index()}
        topic_notes = {slug: [note["text"] for note in self.load_topic_notes(slug)] for slug in topics}
        results = []
        superseded = []
        for topic, note_text in promotions:
            meta = DURABLE_TOPIC_DEFAULTS[topic]
            topics.setdefault(
                topic,
                {
                    "topic": topic,
                    "title": meta["title"],
                    "summary": meta["summary"],
                    "tags": list(meta["tags"]),
                },
            )
            existing = topic_notes.setdefault(topic, [])
            if note_text in existing:
                continue
            new_subject = self._subject_key(note_text)
            replaced = False
            if new_subject:
                for index, old_text in enumerate(list(existing)):
                    if self._subject_key(old_text) == new_subject:
                        superseded.append(f"{topic}: {old_text} -> {note_text}")
                        existing[index] = note_text
                        replaced = True
                        break
            if not replaced:
                existing.append(note_text)
            results.append(f"{topic}: {note_text}")
        self._write_index([topics[slug] for slug in sorted(topics)])
        for topic, notes in topic_notes.items():
            self._write_topic(topic, notes)
        return results, superseded


def _ensure_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if value in (None, ""):
        return []
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


def resolve_workspace_path(raw_path, workspace_root=None):
    path = Path(str(raw_path))
    if workspace_root is None:
        return path

    root = Path(workspace_root).resolve()
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def canonicalize_path(raw_path, workspace_root=None):
    resolved = resolve_workspace_path(raw_path, workspace_root)
    if resolved is None:
        return Path(str(raw_path)).as_posix()
    if workspace_root is None:
        return Path(str(raw_path)).as_posix()
    root = Path(workspace_root).resolve()
    return resolved.relative_to(root).as_posix()


def file_freshness(raw_path, workspace_root=None):
    resolved = resolve_workspace_path(raw_path, workspace_root)
    if resolved is None or not resolved.exists() or not resolved.is_file():
        return None
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def _tokenize(text):
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+", str(text))}


def _parse_timestamp(value):
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return 0.0


def _normalize_note(note, index):
    if isinstance(note, str):
        text = clip(note.strip(), 500)
        return {
            "text": text,
            "tags": [],
            "source": "",
            "created_at": now(),
            "note_index": index,
            "kind": "episodic",
        }

    if not isinstance(note, dict):
        text = clip(str(note).strip(), 500)
        return {
            "text": text,
            "tags": [],
            "source": "",
            "created_at": now(),
            "note_index": index,
            "kind": "episodic",
        }

    text = clip(str(note.get("text", "")).strip(), 500)
    tags = [str(tag).strip() for tag in _ensure_list(note.get("tags", [])) if str(tag).strip()]
    source = str(note.get("source", "")).strip()
    created_at = str(note.get("created_at", "")).strip() or now()
    note_index = int(note.get("note_index", index))
    kind = str(note.get("kind", "episodic")).strip() or "episodic"
    return {
        "text": text,
        "tags": _dedupe_preserve_order(tags),
        "source": source,
        "created_at": created_at,
        "note_index": note_index,
        "kind": kind,
    }


def normalize_memory_state(state, workspace_root=None):
    if state is None:
        state = default_memory_state()
    elif not isinstance(state, dict):
        raise TypeError("memory state must be a mapping")

    # 规范化层的作用，是把“磁盘里可能长得不太一样的旧状态”
    # 统一整理成当前 runtime 可直接使用的紧凑结构。
    working = state.get("working")
    if not isinstance(working, dict):
        working = {}
    working.setdefault("task_summary", "")
    working.setdefault("recent_files", [])
    working["task_summary"] = clip(str(working.get("task_summary", "")).strip(), 300)
    working["recent_files"] = _dedupe_preserve_order(
        [
            canonicalize_path(path, workspace_root)
            for path in _ensure_list(working.get("recent_files", []))
            if str(path).strip()
        ]
    )[-WORKING_FILE_LIMIT:]
    state["working"] = working

    if not str(working["task_summary"]).strip() and state.get("task"):
        working["task_summary"] = clip(str(state.get("task", "")).strip(), 300)
    if not working["recent_files"] and state.get("files"):
        working["recent_files"] = _dedupe_preserve_order(
            [
                canonicalize_path(path, workspace_root)
                for path in _ensure_list(state.get("files", []))
                if str(path).strip()
            ]
        )[-WORKING_FILE_LIMIT:]

    episodic_notes = state.get("episodic_notes")
    if not isinstance(episodic_notes, list):
        episodic_notes = []

    if not episodic_notes and state.get("notes"):
        episodic_notes = [
            _normalize_note(note, index)
            for index, note in enumerate(_ensure_list(state.get("notes", [])))
            if str(note).strip()
        ]
    else:
        normalized_notes = []
        for index, note in enumerate(episodic_notes):
            if isinstance(note, str) and not str(note).strip():
                continue
            normalized_notes.append(_normalize_note(note, index))
        episodic_notes = normalized_notes
    episodic_notes = episodic_notes[-EPISODIC_NOTE_LIMIT:]
    state["episodic_notes"] = episodic_notes

    file_summaries = state.get("file_summaries")
    if not isinstance(file_summaries, dict):
        file_summaries = {}
    normalized_file_summaries = {}
    for path, summary in file_summaries.items():
        path = canonicalize_path(path, workspace_root)
        if isinstance(summary, dict):
            text = clip(str(summary.get("summary", "")).strip(), 500)
            created_at = str(summary.get("created_at", "")).strip() or now()
            freshness = summary.get("freshness")
            freshness = None if freshness in (None, "") else str(freshness).strip() or None
        else:
            text = clip(str(summary).strip(), 500)
            created_at = now()
            freshness = None
        if not path or not text:
            continue
        normalized_file_summaries[path] = {
            "summary": text,
            "created_at": created_at,
            "freshness": freshness,
        }
    state["file_summaries"] = normalized_file_summaries

    next_note_index = state.get("next_note_index")
    if not isinstance(next_note_index, int) or next_note_index < 0:
        next_note_index = 0
    max_index = max([note["note_index"] for note in episodic_notes], default=-1)
    state["next_note_index"] = max(next_note_index, max_index + 1)

    state["task"] = working["task_summary"]
    state["files"] = list(working["recent_files"])
    state["notes"] = [note["text"] for note in episodic_notes]
    durable_root = Path(workspace_root) / ".pico" / "memory" if workspace_root is not None else None
    durable_store = DurableMemoryStore(durable_root) if durable_root is not None else None
    state["durable_topics"] = durable_store.topic_slugs() if durable_store is not None else []
    return state


def set_task_summary(state, summary, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    state["working"]["task_summary"] = clip(str(summary).strip(), 300)
    state["task"] = state["working"]["task_summary"]
    return state


def remember_file(state, path, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    path = canonicalize_path(path, workspace_root).strip()
    if not path:
        return state
    files = [item for item in state["working"]["recent_files"] if item != path]
    files.append(path)
    state["working"]["recent_files"] = files[-WORKING_FILE_LIMIT:]
    state["files"] = list(state["working"]["recent_files"])
    return state


def append_note(state, text, tags=(), source="", created_at=None, workspace_root=None, kind="episodic"):
    state = normalize_memory_state(state, workspace_root)
    text = clip(str(text).strip(), 500)
    if not text:
        return state

    normalized_tags = _dedupe_preserve_order(
        [str(tag).strip() for tag in _ensure_list(tags) if str(tag).strip()]
    )
    note = {
        "text": text,
        "tags": normalized_tags,
        "source": str(source).strip(),
        "created_at": str(created_at).strip() if created_at else now(),
        "note_index": int(state.get("next_note_index", 0)),
        "kind": str(kind).strip() or "episodic",
    }
    state["next_note_index"] = note["note_index"] + 1

    notes = [item for item in state["episodic_notes"] if item["text"] != note["text"]]
    notes.append(note)
    state["episodic_notes"] = notes[-EPISODIC_NOTE_LIMIT:]
    state["notes"] = [item["text"] for item in state["episodic_notes"]]
    return state
def set_file_summary(state, path, summary, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    path = canonicalize_path(path, workspace_root).strip()
    summary = clip(str(summary).strip(), 500)
    if not path or not summary:
        return state
    state["file_summaries"][path] = {
        "summary": summary,
        "created_at": now(),
        "freshness": file_freshness(path, workspace_root),
    }
    return state


def invalidate_file_summary(state, path, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    path = canonicalize_path(path, workspace_root).strip()
    if not path:
        return state
    state["file_summaries"].pop(path, None)
    return state


def invalidate_stale_file_summaries(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    invalidated = []
    for path, summary in list(state["file_summaries"].items()):
        current_freshness = file_freshness(path, workspace_root)
        if summary.get("freshness") == current_freshness:
            continue
        invalidated.append(path)
        state["file_summaries"].pop(path, None)
    return state, invalidated


def summarize_read_result(result, limit=180):
    # 我们不会把完整文件内容塞进记忆层，
    # 这里只保留足够提醒下一轮“刚刚读到了什么”的短摘要。
    lines = [line.strip() for line in str(result).splitlines() if line.strip()]
    if not lines:
        return "(empty)"
    if lines[0].startswith("# "):
        lines = lines[1:]
    if not lines:
        return "(empty)"
    summary = " | ".join(lines[:3])
    return clip(summary, limit)


def retrieval_candidates(state, query, limit=3, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    query_tokens = _tokenize(query)
    ranked = []
    for note in state["episodic_notes"]:
        # 召回逻辑故意保持简单透明：先看 tag 精确命中，
        # 再看关键词重叠，最后看新旧程度。这里不引入 embedding。
        note_tags = {tag.lower() for tag in note.get("tags", [])}
        note_tokens = _tokenize(note.get("text", "")) | _tokenize(note.get("source", "")) | note_tags
        exact_tag_match = int(bool(query_tokens & note_tags))
        keyword_overlap = len(query_tokens & note_tokens)
        if exact_tag_match == 0 and keyword_overlap == 0:
            continue
        recency = _parse_timestamp(note.get("created_at"))
        note_index = int(note.get("note_index", 0))
        ranked.append(((exact_tag_match, keyword_overlap, recency, note_index), note))

    if workspace_root is not None:
        durable_store = DurableMemoryStore(Path(workspace_root) / ".pico" / "memory")
        for note in durable_store.retrieval_candidates(query, limit=limit):
            note_tags = {tag.lower() for tag in note.get("tags", [])}
            note_tokens = _tokenize(note.get("text", "")) | _tokenize(note.get("source", "")) | note_tags
            exact_tag_match = int(bool(query_tokens & note_tags))
            keyword_overlap = len(query_tokens & note_tokens)
            recency = _parse_timestamp(note.get("created_at"))
            ranked.append(((exact_tag_match, keyword_overlap, recency, -1), note))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in ranked[:limit]]


def retrieval_view(state, query, limit=3, workspace_root=None):
    candidates = retrieval_candidates(state, query, limit=limit, workspace_root=workspace_root)
    lines = ["Relevant memory:"]
    if not candidates:
        lines.append("- none")
        return "\n".join(lines)
    for note in candidates:
        lines.append(f"- {note['text']}")
    return "\n".join(lines)


def render_memory_text(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    # 这里渲染的是给模型看的紧凑“仪表盘”，不是完整回放。
    # 笔记正文默认不展开，只有在相关召回时才按需拿出来。
    lines = [
        "Memory:",
        f"- task: {state['working']['task_summary'] or '-'}",
        f"- recent_files: {', '.join(state['working']['recent_files']) or '-'}",
    ]

    summaries = []
    for path in state["working"]["recent_files"][:FILE_SUMMARY_LIMIT]:
        summary = state["file_summaries"].get(path, {})
        current_freshness = file_freshness(path, workspace_root)
        if summary.get("summary", "") and summary.get("freshness") == current_freshness:
            summaries.append(f"- {path}: {summary['summary']}")
    if summaries:
        lines.append("- file_summaries:")
        lines.extend(f"  {line}" for line in summaries)
    else:
        lines.append("- file_summaries: -")

    lines.append(f"- episodic_notes: {len(state['episodic_notes'])}")
    durable_topics = state.get("durable_topics", [])
    lines.append(f"- durable_topics: {', '.join(durable_topics) or '-'}")
    return "\n".join(lines)


def is_effectively_empty(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    return (
        not str(state["working"]["task_summary"]).strip()
        and not state["working"]["recent_files"]
        and not state["episodic_notes"]
        and not state["file_summaries"]
    )


class LayeredMemory:
    def __init__(self, state=None, workspace_root=None):
        self.workspace_root = workspace_root
        self.state = normalize_memory_state(state, workspace_root)
        self.durable_store = DurableMemoryStore(Path(workspace_root) / ".pico" / "memory") if workspace_root is not None else None

    def to_dict(self):
        self.state = normalize_memory_state(self.state, self.workspace_root)
        return self.state

    def canonical_path(self, path):
        return canonicalize_path(path, self.workspace_root)

    def set_task_summary(self, summary):
        self.state = set_task_summary(self.state, summary, self.workspace_root)
        return self

    def remember_file(self, path):
        self.state = remember_file(self.state, path, self.workspace_root)
        return self

    def append_note(self, text, tags=(), source="", created_at=None, kind="episodic"):
        self.state = append_note(
            self.state,
            text,
            tags=tags,
            source=source,
            created_at=created_at,
            workspace_root=self.workspace_root,
            kind=kind,
        )
        return self

    def set_file_summary(self, path, summary):
        self.state = set_file_summary(self.state, path, summary, self.workspace_root)
        return self

    def invalidate_file_summary(self, path):
        self.state = invalidate_file_summary(self.state, path, self.workspace_root)
        return self

    def invalidate_stale_file_summaries(self):
        self.state, invalidated = invalidate_stale_file_summaries(self.state, self.workspace_root)
        return invalidated

    def retrieval_candidates(self, query, limit=3):
        return retrieval_candidates(self.state, query, limit=limit, workspace_root=self.workspace_root)

    def retrieval_view(self, query, limit=3):
        return retrieval_view(self.state, query, limit=limit, workspace_root=self.workspace_root)

    def render_memory_text(self):
        return render_memory_text(self.state, self.workspace_root)

    def promote_durable(self, promotions):
        if self.durable_store is None:
            return [], []
        self.state = normalize_memory_state(self.state, self.workspace_root)
        promoted, superseded = self.durable_store.promote(promotions)
        self.state = normalize_memory_state(self.state, self.workspace_root)
        return promoted, superseded
