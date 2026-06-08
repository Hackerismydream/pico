import re
from pathlib import Path

ENTRYPOINT_NAME = "MEMORY.md"
MAX_ENTRYPOINT_LINES = 200
DREAM_DIR_NAME = ".dream"
LOCK_FILE_NAME = ".consolidate-lock"

SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{6,}|ghp_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_ -]?key|token|secret|password)\s*[:=]\s*\S{8,})"
)
SECRET_KEYWORD_PATTERN = re.compile(r"(?i)\b(api[_ -]?key|token|secret|password)\b")
RAW_OUTPUT_PATTERN = re.compile(r"(?im)^(stdout|stderr|exit_code)\s*:|^Traceback \(most recent call last\):")
BASE64_LIKE_PATTERN = re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b")
ALLOWED_DURABLE_TYPES = {"user", "feedback", "project", "reference"}
TRANSIENT_MEMORY_PREFIXES = (
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


def _frontmatter(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    metadata = {}
    for raw in text[4:end].splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata


def _legacy_topic_metadata(text):
    metadata = {}
    for raw in text.splitlines()[:20]:
        line = raw.strip()
        if line.startswith("- topic:"):
            metadata["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("- summary:"):
            metadata["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("- tags:"):
            metadata.setdefault("type", "project")
    return metadata or None


def lint_memory_candidate(candidate_root):
    candidate_root = Path(candidate_root)
    issues = []
    warnings = []
    index_path = candidate_root / ENTRYPOINT_NAME
    if not index_path.exists():
        issues.append({"severity": "error", "code": "missing_index", "path": ENTRYPOINT_NAME})
    else:
        index_text = index_path.read_text(encoding="utf-8", errors="replace")
        index_lines = index_text.splitlines()
        if len(index_lines) > MAX_ENTRYPOINT_LINES:
            issues.append({"severity": "error", "code": "index_too_long", "path": ENTRYPOINT_NAME, "lines": len(index_lines)})
        if len(index_text.encode("utf-8")) > 25_000:
            issues.append({"severity": "error", "code": "index_too_large", "path": ENTRYPOINT_NAME})
        for match in re.finditer(r"\]\(([^)]+)\)", index_text):
            target = match.group(1).strip()
            if "://" in target or target.startswith("#"):
                continue
            target_path = (candidate_root / target).resolve()
            try:
                target_path.relative_to(candidate_root.resolve())
            except ValueError:
                issues.append({"severity": "error", "code": "index_link_escapes", "path": ENTRYPOINT_NAME, "target": target})
                continue
            if not target_path.exists():
                issues.append({"severity": "error", "code": "broken_index_link", "path": ENTRYPOINT_NAME, "target": target})

    for relative, text in _managed_file_texts(candidate_root).items():
        if not _is_official_memory_payload(relative):
            warnings.append({"severity": "warning", "code": "ignored_non_memory_payload", "path": relative})
            continue
        lowered = text.lower()
        if SECRET_VALUE_PATTERN.search(text) or BASE64_LIKE_PATTERN.search(text):
            issues.append({"severity": "error", "code": "secret_shaped", "path": relative})
        elif SECRET_KEYWORD_PATTERN.search(text):
            warnings.append({"severity": "warning", "code": "secret_keyword", "path": relative})
        if RAW_OUTPUT_PATTERN.search(text):
            issues.append({"severity": "error", "code": "raw_output", "path": relative})
        for prefix in TRANSIENT_MEMORY_PREFIXES:
            if prefix.lower() in lowered:
                issues.append({"severity": "error", "code": "transient_task_state", "path": relative, "match": prefix})
                break
        if relative == ENTRYPOINT_NAME:
            continue
        if relative.endswith(".md"):
            metadata = _frontmatter(text) or _legacy_topic_metadata(text)
            if metadata is None:
                warnings.append({"severity": "warning", "code": "missing_frontmatter", "path": relative})
                continue
            missing = [key for key in ("name", "description", "type") if not metadata.get(key)]
            if missing:
                warnings.append({"severity": "warning", "code": "incomplete_metadata", "path": relative, "missing": missing})
            memory_type = str(metadata.get("type", "")).strip()
            if memory_type and memory_type not in ALLOWED_DURABLE_TYPES:
                issues.append({"severity": "error", "code": "invalid_type", "path": relative, "type": memory_type})

    status = "failed" if issues else "warning" if warnings else "passed"
    return {"status": status, "errors": issues, "warnings": warnings}
