"""Session compaction boundary."""

import re

from .context_usage import estimate_tokens
from .workspace import now


CONSTRAINT_PATTERNS = (
    "不要",
    "不能",
    "必须",
    "只",
    "不改",
    "保持",
    "除了",
    "don't",
    "must",
    "only",
    "keep",
    "never",
    "always",
    "do not",
    "without changing",
    "preserve",
)

DECISION_PATTERNS = (
    "decided",
    "选择",
    "因为",
    "approach",
    "改用",
    "放弃",
    "instead",
    "rather than",
    "switched to",
)

ERROR_PATTERNS = (
    "Error",
    "error:",
    "failed",
    "失败",
    "Traceback",
    "FAILED",
    "AssertionError",
    "TypeError",
    "KeyError",
)


class CompactManager:
    def __init__(self, agent):
        self.agent = agent

    def compact(self, trigger="manual", keep_recent_turns=2):
        history = list(self.agent.session.get("history", []))
        groups = self._group(history)
        if len(groups) <= keep_recent_turns:
            summary = self._summary(trigger, history, history, "")
            self.agent.session_event_bus.emit("compaction_created", summary)
            return summary

        compacted_turns = groups[:-keep_recent_turns]
        kept_turns = groups[-keep_recent_turns:]
        compacted_items = [item for _, items in compacted_turns for item in items]
        kept_items = [item for _, items in kept_turns for item in items]
        summary_text = self._summary_text(compacted_items)
        summary_item = self.agent.turn_history.enrich(
            {
                "role": "system",
                "kind": "compact_summary",
                "content": summary_text,
                "created_at": now(),
                "source": "compact",
            }
        )
        self.agent.session["history"] = [summary_item, *kept_items]
        summary = self._summary(trigger, history, self.agent.session["history"], summary_text)
        self.agent.session.setdefault("compactions", []).append(summary)
        self.agent.session_path = self.agent.session_store.save(self.agent.session)
        self.agent.session_event_bus.emit("compaction_created", summary)
        if self.agent.current_task_state:
            self.agent.emit_trace(self.agent.current_task_state, "compaction_started", {"trigger": trigger, "pre_tokens": summary["pre_tokens"]})
            self.agent.emit_trace(self.agent.current_task_state, "compaction_finished", summary)
        return summary

    @staticmethod
    def _group(history):
        groups = []
        by_id = {}
        for item in history:
            turn_id = str(item.get("turn_id") or "legacy")
            if turn_id not in by_id:
                by_id[turn_id] = []
                groups.append((turn_id, by_id[turn_id]))
            by_id[turn_id].append(item)
        return groups

    def _summary(self, trigger, before, after, summary_text):
        pre_chars = sum(len(str(item.get("content", ""))) for item in before)
        post_chars = sum(len(str(item.get("content", ""))) for item in after)
        return {
            "trigger": str(trigger),
            "created_at": now(),
            "pre_tokens": estimate_tokens(pre_chars),
            "post_tokens": estimate_tokens(post_chars),
            "pre_items": len(before),
            "post_items": len(after),
            "summary_chars": len(summary_text),
        }

    def _summary_text(self, items):
        def sentences(text):
            parts = re.split(r"[。！？!?]+|\n+|\.(?:\s+|$)", str(text))
            return [part.strip(" \t\r\n:;,.，；、") for part in parts if part.strip()]

        def matches(text, patterns):
            lowered = text.lower()
            return any(str(pattern).lower() in lowered for pattern in patterns)

        def add_unique(values, value, limit):
            value = value.strip()
            if value and value not in values and len(values) < limit:
                values.append(value)

        rejected_patterns = (
            "tried",
            "but",
            "不行",
            "reverted",
            "doesn't work",
            "didn't work",
            "does not work",
        )
        files_read = []
        files_modified = []
        user_requests = []
        user_constraints = []
        key_decisions = []
        rejected_paths = []
        critical_artifacts = []
        for item in items:
            artifact_ref = str(item.get("artifact_ref", "")).strip()
            if artifact_ref and artifact_ref not in critical_artifacts:
                critical_artifacts.append(artifact_ref)
            if item.get("role") == "user":
                content = str(item.get("content", "")).strip()
                user_requests.append(content)
                for sentence in sentences(content):
                    if matches(sentence, CONSTRAINT_PATTERNS):
                        add_unique(user_constraints, sentence, 5)
            elif item.get("role") == "assistant":
                content = str(item.get("content", "")).strip()
                for sentence in sentences(content):
                    if matches(sentence, DECISION_PATTERNS):
                        add_unique(key_decisions, sentence, 3)
                    lowered = sentence.lower()
                    tried_but = "tried" in lowered and "but" in lowered
                    if tried_but or matches(sentence, rejected_patterns[2:]):
                        add_unique(rejected_paths, sentence, 3)
            elif item.get("role") == "tool":
                path = str(item.get("args", {}).get("path", "")).strip()
                if item.get("name") == "read_file" and path:
                    files_read.append(path)
                if item.get("name") in {"write_file", "patch_file"} and path:
                    files_modified.append(path)
        last_error_context = "-"
        for item in reversed(items):
            if item.get("role") != "tool":
                continue
            content = str(item.get("content", "")).strip()
            if content and matches(content, ERROR_PATTERNS):
                last_error_context = content[:200]
                break

        def joined(values):
            return "; ".join(values) if values else "-"

        summary = "\n".join(
            [
                "Compacted session summary:",
                f"- Goal: {user_requests[-1] if user_requests else '-'}",
                f"- User constraints: {joined(user_constraints)}",
                f"- Files read: {', '.join(sorted(set(files_read))) or '-'}",
                f"- Files modified: {', '.join(sorted(set(files_modified))) or '-'}",
                f"- Key decisions: {joined(key_decisions)}",
                f"- Rejected paths: {joined(rejected_paths)}",
                f"- Last error context: {last_error_context}",
                f"- Critical artifacts: {', '.join(critical_artifacts) if critical_artifacts else '-'}",
                f"- Current progress: compacted {len(items)} history items",
                "- Next step: continue from the latest preserved turn",
            ]
        )
        if len(summary) > 2000:
            return summary[:1997].rstrip() + "..."
        return summary
